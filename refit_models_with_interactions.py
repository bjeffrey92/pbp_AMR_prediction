import logging
import pickle
from functools import lru_cache
from math import ceil
from random import choice
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from nptyping import NDArray
from scipy.sparse import csr_matrix
from sklearn.linear_model import Lasso
from sklearn.metrics import mean_squared_error

from interrogate_rf import load_model
from models import fit_model, load_data, optimise_hps
from parse_random_forest import DecisionTree_, valid_feature_pair
from utils import ResultsContainer, accuracy, mean_acc_per_bin


def map_loci(interacting_loci: NDArray) -> Dict[int, int]:
    loci = set(
        [i[0] for i in interacting_loci] + [i[1] for i in interacting_loci]
    )
    return {i: ceil((i + 1) / 20) for i in loci}


def plot_interactions(model: Lasso, interactions: List[Tuple[int, int]]):
    non_zero_coef = np.where(model.coef_ != 0)[0]
    interactions_array = np.array(interactions)
    interacting_loci = interactions_array[non_zero_coef]

    return map_loci(interacting_loci)


@lru_cache(maxsize=1)
def get_included_features():
    model = load_model()

    # extract each decision tree from the rf
    trees = [DecisionTree_(dt) for dt in model.estimators_]

    # get all the features which were included in the model
    included_features = np.unique(
        np.concatenate([tree.internal_node_features for tree in trees])
    )

    return included_features


def simulate_random_interactions(n: int) -> List[Tuple[int, int]]:
    included_features = get_included_features()
    feature_pairs: List[Tuple[int, int]] = []
    while len(feature_pairs) < n:
        fp = (choice(included_features), choice(included_features))
        if valid_feature_pair(*fp):
            feature_pairs.append(fp)

    return feature_pairs


def random_interaction_model_fits(n: int, model_type: str = "lasso") -> float:
    """
    n: number of interaction terms to simulate
    """
    interactions = simulate_random_interactions(n)

    train, test, _ = load_data(
        blosum_inference=True, interactions=tuple(interactions)
    )

    # just interaction terms
    train = (csr_matrix(train[0].todense()[:, -len(interactions) :]), train[1])
    test = (csr_matrix(test[0].todense()[:, -len(interactions) :]), test[1])

    model = fit_model(train, model_type, alpha=0.05)
    test_predictions = model.predict(test[0])

    MSE = mean_squared_error(test[1], test_predictions)
    print(MSE)
    return MSE


def plot_simulations(n_interactions: int, test_data_mse: int):
    random_interaction_MSEs = [
        random_interaction_model_fits(n_interactions) for i in range(100)
    ]

    plt.clf()
    sns.displot(random_interaction_MSEs)
    plt.title("Histogram of MSE of model fitted to random interactions")
    plt.xlabel("MSE of lasso model")
    plt.axvline(test_data_mse, dashes=(1, 1))
    plt.tight_layout()
    plt.savefig("histogram_simulated_interactions.png")

    plt.clf()
    sns.displot(random_interaction_MSEs, kind="kde")
    plt.title("Kernel Density Estimation of the PDF")
    plt.xlabel("MSE of lasso model")
    plt.axvline(test_data_mse, dashes=(1, 1))
    plt.tight_layout()
    plt.savefig("KDE_simulated_interactions.png")

    plt.clf()
    sns.displot(random_interaction_MSEs, kind="ecdf")
    plt.title("Empirical CDF")
    plt.xlabel("MSE of lasso model")
    plt.axvline(test_data_mse, dashes=(1, 1))
    plt.tight_layout()
    plt.savefig("CDF_simulated_interactions.png")
    plt.clf()


def compare_interaction_model_with_rf(results: ResultsContainer):
    model = load_model()
    testing_data = load_data(interactions=None, blosum_inference=True)[1]
    rf_predictions = model.predict(testing_data[0])

    plt.clf()
    sns.kdeplot(testing_data[1], label="Testing Data")
    sns.kdeplot(rf_predictions, label="RF Predictions")
    sns.kdeplot(
        results.testing_predictions, label="Interaction Model Predictions"
    )
    plt.legend()
    plt.xlabel("Log2(MIC)")
    plt.title("RF vs Lasso Interaction Model")
    plt.tight_layout()
    plt.savefig("RF_vs_lasso_interaction_model_predictions.png")


def main():

    model_type = "lasso"
    pbounds = {"alpha": [0.05, 1.95]}

    logging.info("Loading inferred interaction data")
    with open("paired_sf_p_values.pkl", "rb") as a:
        paired_sf_p_values = pickle.load(a)

    # lowest p values are smaller than smallest 64 bit floating point number
    interactions = [i[0] for i in paired_sf_p_values if i[1] == 0]

    train, test, validate = load_data(
        blosum_inference=True, interactions=interactions
    )

    logging.info("Optimising the model for the test data accuracy")
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
    )

    plot_simulations(
        results.model.sparse_coef_.count_nonzero(), results.testing_MSE
    )


if __name__ == "__main__":
    logging.basicConfig()
    logging.root.setLevel(logging.INFO)

    main()
