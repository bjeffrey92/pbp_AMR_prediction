import logging
import os
import pickle
import warnings
from functools import partial
from math import log10
from typing import Dict, Tuple, Union, Set

import pandas as pd
import numpy as np
from bayes_opt import BayesianOptimization
from nptyping import NDArray
from scipy.sparse import csr_matrix
from sklearn.ensemble import RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import ElasticNet, Lasso
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split

from data_preprocessing.parse_pbp_data import (
    encode_sequences,
    parse_cdc,
    parse_pmen,
    standardise_MICs,
)
from model_analysis.parse_random_forest import DecisionTree_
from models.supervised_models import _fit_rf, _fit_en, _fit_lasso
from models.unsupervised_models import _fit_DBSCAN, _fit_DBSCAN_with_UMAP
from utils import (
    ResultsContainer,
    accuracy,
    closest_blosum_sequence,
    mean_acc_per_bin,
    parse_blosum_matrix,
)


def fit_model(
    train: Tuple[Union[csr_matrix, NDArray], NDArray],
    model_type: str,
    **kwargs,
) -> Union[ElasticNet, Lasso, RandomForestRegressor]:
    if model_type == "random_forest":
        reg = _fit_rf(train, **kwargs)

    elif model_type == "DBSCAN":
        reg = _fit_DBSCAN(train, **kwargs)

    elif model_type == "DBSCAN_with_UMAP":
        reg = _fit_DBSCAN_with_UMAP(train, **kwargs)

    else:
        # lasso and en models require iterative fitting
        max_iter = 100000
        fitted = False
        while not fitted:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                if model_type == "elastic_net":
                    reg = _fit_en(train, max_iter, **kwargs)
                elif model_type == "lasso":
                    reg = _fit_lasso(train, max_iter, **kwargs)
                else:
                    raise NotImplementedError(model_type)

                if len(w) > 1:
                    for warning in w:
                        logging.error(warning.category)
                    raise Exception
                elif w and issubclass(w[0].category, ConvergenceWarning):
                    logging.warning(
                        f"Failed to converge with max_iter = {max_iter}, "
                        + "adding 100000 more"
                    )
                    max_iter += 100000
                else:
                    fitted = True

    return reg


def train_evaluate(
    train: Tuple[Union[NDArray, csr_matrix], NDArray],
    test: Tuple[Union[NDArray, csr_matrix], NDArray],
    model_type: str,
    **kwargs,
) -> float:
    reg = fit_model(train, model_type, **kwargs)
    MSE = mean_squared_error(test[1], reg.predict(test[0]))
    return -MSE  # pylint: disable=invalid-unary-operand-type


def optimise_hps(
    train: Tuple[Union[NDArray, csr_matrix], NDArray],
    test: Tuple[Union[NDArray, csr_matrix], NDArray],
    pbounds: Dict[str, Tuple[float, float]],
    model_type: str,
    init_points: int = 5,
    n_iter: int = 10,
) -> BayesianOptimization:
    partial_fitting_function = partial(
        train_evaluate, train=train, test=test, model_type=model_type
    )

    optimizer = BayesianOptimization(
        f=partial_fitting_function, pbounds=pbounds, random_state=0
    )
    optimizer.maximize(init_points=init_points, n_iter=n_iter)

    return optimizer


def filter_features_by_previous_model_fit(
    model_path: str,
    training_features: csr_matrix,
    testing_features: csr_matrix,
    validation_features: csr_matrix,
) -> Tuple[csr_matrix, csr_matrix, csr_matrix]:

    with open(model_path, "rb") as a:
        original_model = pickle.load(a)
    if isinstance(original_model, ResultsContainer):
        original_model = original_model.model
    elif not isinstance(original_model, RandomForestRegressor):
        raise TypeError(f"Unknown input of type {type(original_model)}")

    # extract each decision tree from the rf
    trees = [DecisionTree_(dt) for dt in original_model.estimators_]

    # get all the features which were included in the model
    included_features = np.unique(
        np.concatenate([tree.internal_node_features for tree in trees])
    )

    filtered_features = []
    for features in [training_features, testing_features, validation_features]:
        features = features.todense()
        filtered_features.append(csr_matrix(features[:, included_features]))

    return tuple(filtered_features)  # type: ignore


# filters data by pbp types which appear in training data
def _filter_data(data, train_types, pbp_type, invert=False):
    inc_types = set(data[pbp_type])
    inc_types = filter(lambda x: x in train_types, inc_types)  # type: ignore
    if invert:
        return data.loc[~data[pbp_type].isin(list(inc_types))]
    else:
        return data.loc[data[pbp_type].isin(list(inc_types))]


def perform_blosum_inference(
    pbp_type: str,
    pbp: str,
    train_types: Set,
    training_data: pd.DataFrame,
    testing_data: pd.DataFrame,
) -> pd.DataFrame:

    pbp_seq = f"{pbp}_seq"

    blosum_scores = parse_blosum_matrix()

    missing_types_and_sequences = _filter_data(
        testing_data, train_types, pbp_type, invert=True
    )[[pbp_type, pbp_seq]].drop_duplicates()

    training_types_and_sequences = training_data[
        [pbp_type, pbp_seq]
    ].drop_duplicates()

    training_sequence_array = np.vstack(
        training_types_and_sequences[pbp_seq].apply(
            lambda x: np.array(list(x))
        )
    )  # stack sequences in the training data as array of characters

    inferred_sequences = missing_types_and_sequences.apply(
        closest_blosum_sequence,
        axis=1,
        pbp=pbp,
        training_sequence_array=training_sequence_array,
        blosum_scores=blosum_scores,
    )
    inferred_sequences = inferred_sequences.apply(pd.Series)
    inferred_sequences.rename(
        columns={
            0: "original_type",
            1: "inferred_seq",
            2: "inferred_type",
        },
        inplace=True,
    )

    testing_data = testing_data.merge(
        inferred_sequences,
        left_on=pbp_type,
        right_on="original_type",
        how="left",
    )
    testing_data[pbp_type].mask(
        ~testing_data.inferred_type.isna(),
        testing_data.inferred_type,
        inplace=True,
    )
    testing_data[pbp_seq].mask(
        ~testing_data.inferred_seq.isna(),
        testing_data.inferred_seq,
        inplace=True,
    )

    return testing_data[training_data.columns]


def cut_down_training_data(
    df: pd.DataFrame, log_threshold: float, sample_fraction: float
) -> pd.DataFrame:
    """
    Removes random subsample of training data within region of high MIC density
    """
    threshold = 2 ** log_threshold
    above_threshold = df.loc[df.mic > threshold]
    below_threshold_sample = df.loc[df.mic <= threshold].sample(
        frac=sample_fraction, random_state=1
    )
    return pd.concat([above_threshold, below_threshold_sample])


def load_data(
    validation_data,
    *,
    interactions: Tuple[Tuple[int]] = None,
    blosum_inference: bool = False,
    filter_unseen: bool = True,
    reduce_training_data=False,
    standardise_training_MIC=False,
    standardise_test_and_val_MIC=False,
) -> Tuple[
    Tuple[csr_matrix, pd.Series],
    Tuple[csr_matrix, pd.Series],
    Tuple[csr_matrix, pd.Series],
]:
    """
    validation_data should be either 'maela' or 'pmen'
    """

    if blosum_inference and filter_unseen:
        raise ValueError(
            "Blosum inference and filtering of unseen samples cannot be applied together"  # noqa: E501
        )

    cdc = pd.read_csv("../data/pneumo_pbp/cdc_seqs_df.csv")
    if validation_data == "pmen":
        val = pd.read_csv("../data/pneumo_pbp/pmen_pbp_profiles_extended.csv")
    elif validation_data == "maela":
        val = pd.read_csv("../data/pneumo_pbp/maela_aa_df.csv")

    if reduce_training_data:
        cdc = cut_down_training_data(cdc, -3.5, 0.5)

    pbp_patterns = ["a1", "b2", "x2"]

    cdc = parse_cdc(cdc, pbp_patterns)
    train, test = train_test_split(cdc, test_size=0.33, random_state=0)
    val = parse_pmen(val, cdc, pbp_patterns)

    if standardise_training_MIC:
        train = standardise_MICs(train)
    if standardise_test_and_val_MIC:
        test = standardise_MICs(test)
        val = standardise_MICs(val)

    for pbp in pbp_patterns:
        pbp_type = f"{pbp}_type"
        train_types = set(train[pbp_type])

        # get closest type to all missing in the training data
        if blosum_inference:
            test = perform_blosum_inference(
                pbp_type, pbp, train_types, train, test
            )
            val = perform_blosum_inference(
                pbp_type, pbp, train_types, train, val
            )

        # filter out everything which isnt in the training data
        elif filter_unseen:
            val = _filter_data(val, train_types, pbp_type)
            test = _filter_data(test, train_types, pbp_type)

    train_encoded_sequences = encode_sequences(train, pbp_patterns)
    test_encoded_sequences = encode_sequences(test, pbp_patterns)
    val_encoded_sequences = encode_sequences(val, pbp_patterns)

    X_train, y_train = train_encoded_sequences, train.log2_mic
    X_test, y_test = test_encoded_sequences, test.log2_mic
    X_validate, y_validate = val_encoded_sequences, val.log2_mic

    def interact(data, interacting_features):
        interacting_features = np.concatenate(
            [np.multiply(data[:, i[0]], data[:, i[1]]) for i in interactions],
            axis=1,
        )
        return csr_matrix(interacting_features)

    if interactions is not None:
        X_train = interact(X_train.todense(), interactions)
        X_test = interact(X_test.todense(), interactions)
        X_validate = interact(X_validate.todense(), interactions)

    return (X_train, y_train), (X_test, y_test), (X_validate, y_validate)


def save_output(results: ResultsContainer, filename: str, outdir: str):
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    # dont overwrite existing results file
    file_path = os.path.join(outdir, filename)
    i = 1
    while os.path.isfile(file_path):
        split_path = file_path.split(".")
        file_path = "".join(split_path[:-1]) + f"({i})" + split_path[-1]
        i += 1

    with open(file_path, "wb") as a:
        pickle.dump(results, a)


def main(
    model_type="random_forest",
    blosum_inference=True,
    validation_data="pmen",
    standardise_training_MIC=True,
    standardise_test_and_val_MIC=False,
    previous_rf_model=None,
):

    logging.info("Loading data")
    train, test, validate = load_data(
        validation_data,
        blosum_inference=blosum_inference,
        filter_unseen=not blosum_inference,
        standardise_training_MIC=standardise_training_MIC,
        standardise_test_and_val_MIC=standardise_test_and_val_MIC,
    )

    # filter features by things which have been used by previously fitted model
    if previous_rf_model is not None:
        filtered_features = filter_features_by_previous_model_fit(
            previous_rf_model, train[0], test[0], validate[0]
        )
        train = (filtered_features[0], train[1])
        test = (filtered_features[1], test[1])
        validate = (filtered_features[2], validate[1])

    logging.info("Optimising the model for the test data accuracy")
    if model_type == "elastic_net":
        pbounds = {"l1_ratio": [0.05, 0.95], "alpha": [0.05, 1.95]}
    elif model_type == "lasso":
        pbounds = {"alpha": [0.05, 1.95]}
    elif model_type == "random_forest":
        pbounds = {
            "n_estimators": [1000, 10000],
            "max_depth": [2, 5],
            "min_samples_split": [2, 10],
            "min_samples_leaf": [2, 2],
        }
    elif model_type == "DBSCAN":
        pbounds = {
            "log_eps": [log10(0.0001), log10(0.1)],
            "min_samples": [2, 20],
        }
    elif model_type == "DBSCAN_with_UMAP":
        pbounds = {
            "log_eps": [log10(0.1), log10(10)],
            "min_samples": [2, 20],
            "umap_components": [2, 15],
        }
    else:
        raise NotImplementedError(model_type)

    optimizer = optimise_hps(
        train, test, pbounds, model_type
    )  # select hps using GP

    logging.info(
        f"Fitting model with optimal hyperparameters: {optimizer.max['params']}"  # noqa: E501
    )
    model = fit_model(
        train, model_type=model_type, **optimizer.max["params"]
    )  # get best model fit

    train_predictions = model.predict(train[0])
    test_predictions = model.predict(test[0])
    validate_predictions = model.predict(validate[0])

    results = ResultsContainer(  # noqa: F841
        training_predictions=train_predictions,
        testing_predictions=test_predictions,
        validation_predictions=validate_predictions,
        training_MSE=mean_squared_error(train[1], train_predictions),
        testing_MSE=mean_squared_error(test[1], test_predictions),
        validation_MSE=mean_squared_error(validate[1], validate_predictions),
        training_accuracy=accuracy(train_predictions, train[1]),
        testing_accuracy=accuracy(test_predictions, test[1]),
        validation_accuracy=accuracy(validate_predictions, validate[1]),
        training_mean_acc_per_bin=mean_acc_per_bin(
            train_predictions, train[1]
        ),
        testing_mean_acc_per_bin=mean_acc_per_bin(test_predictions, test[1]),
        validation_mean_acc_per_bin=mean_acc_per_bin(
            validate_predictions, validate[1]
        ),
        hyperparameters=optimizer.max["params"],
        model_type=model_type,
        model=model,
        config={
            "blosum_inference": blosum_inference,
            "filter_unseen": not blosum_inference,
            "validation_data": validation_data,
            "standardise_training_MIC": standardise_training_MIC,
            "standardise_test_and_val_MIC": standardise_test_and_val_MIC,
            "previous_rf_model": previous_rf_model,
        },
        optimizer=optimizer,
    )

    outdir = f"results/{model_type}"
    if blosum_inference:
        filename = f"{validation_data}_results_blosum_inferred_pbp_types.pkl"
    else:
        filename = f"{validation_data}_results_filtered_pbp_types.pkl"
    save_output(results, filename, outdir)


if __name__ == "__main__":
    logging.basicConfig()
    logging.root.setLevel(logging.INFO)

    main()
