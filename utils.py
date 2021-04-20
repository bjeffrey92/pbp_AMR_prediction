from functools import lru_cache
from typing import Dict, Any

import pandas as pd
import numpy as np
import nptyping
from dataclasses import dataclass


def accuracy(
    predictions: nptyping.NDArray[nptyping.Float],
    labels: nptyping.NDArray[nptyping.Float],
) -> float:
    """
    Prediction accuracy defined as percentage of predictions within 1 twofold
    dilution of true value
    """
    diff = abs(predictions - labels)
    correct = diff[[i < 1 for i in diff]]
    return len(correct) / len(predictions) * 100


def mean_acc_per_bin(
    predictions: nptyping.NDArray[nptyping.Float],
    labels: nptyping.NDArray[nptyping.Float],
) -> float:
    """
    Splits labels into bins of size = bin_size, and calculates the prediction
    accuracy in each bin.
    Returns the mean accuracy across all bins
    """
    assert len(predictions) == len(labels)

    # apply Freedman-Diaconis rule to get optimal bin size
    # https://en.wikipedia.org/wiki/Freedman%E2%80%93Diaconis_rule
    IQR = np.subtract(*np.percentile(labels, [75, 25]))
    bin_size = 2 * IQR / (len(labels) ** (1 / 3))
    bin_size = int(
        np.ceil(bin_size)
    )  # round up cause if less than 1 will not work with accuracy function

    min_value = int(np.floor(min(labels)))
    max_value = int(np.floor(max(labels)))
    bins = list(range(min_value, max_value + bin_size, bin_size))
    binned_labels = np.digitize(labels, bins)

    df = pd.DataFrame(
        {
            "labels": labels,
            "predictions": predictions,
            "binned_labels": binned_labels,
        }
    )  # to allow quick searches across bins

    # percentage accuracy per bin
    def _get_accuracy(d):
        acc = accuracy(
            d.labels.to_numpy(),
            d.predictions.to_numpy(),
        )
        return acc

    bin_accuracies = df.groupby(df.binned_labels).apply(_get_accuracy)

    return bin_accuracies.mean()


@lru_cache(maxsize=1)
def parse_blosum_matrix() -> Dict[str, Dict[str, int]]:
    # return as dict cause quicker to search
    df = pd.read_csv("blosum62.csv", index_col=0)
    return {i: df[i].to_dict() for i in df.columns}


def closest_blosum_sequence(
    pbp_data: pd.Series,
    pbp: str,
    training_types_and_sequences: pd.DataFrame,
    blosum_scores: pd.DataFrame,
):
    """
    pbp: the pbp to match
    pbp_data: series with type and sequence of pbp not in training_data
    training_data: data to be used to find closest pbp based on blosum62
    """
    pbp_seq = f"{pbp}_seq"
    pbp_type = f"{pbp}_type"

    pbp_sequence = pbp_data[pbp_seq]

    def get_blosum_score(seq1, seq2=pbp_sequence):
        return sum(blosum_scores[a][b] for a, b in zip(seq1, seq2))

    scores = training_types_and_sequences[pbp_seq].apply(get_blosum_score)
    closest_type = training_types_and_sequences.loc[
        scores == scores.max()
    ].head(
        1
    )  # takes first if there are multiple sequences with same distance
    closest_type["original_type"] = pbp_data[pbp_type]
    closest_type.rename(
        columns={pbp_type: "inferred_type", pbp_seq: "inferred_seq"},
        inplace=True,
    )

    return closest_type


@dataclass(unsafe_hash=True)
class ResultsContainer:
    training_accuracy: float
    testing_accuracy: float
    validation_accuracy: float

    training_MSE: float
    testing_MSE: float
    validation_MSE: float

    training_mean_acc_per_bin: float
    testing_mean_acc_per_bin: float
    validation_mean_acc_per_bin: float

    training_predictions: nptyping.NDArray[nptyping.Float]
    testing_predictions: nptyping.NDArray[nptyping.Float]
    validation_predictions: nptyping.NDArray[nptyping.Float]

    hyperparameters: Dict[str, float]

    model_type: str

    model: Any

    def __repr__(self):
        return (
            f"model: {self.model_type}\n"
            + f"model_hyperparameters: {self.hyperparameters},\n"
            + "\n"
            + "ACCURACY\n"
            + f"Training Data Accuracy = {self.training_accuracy}\n"
            + f"Testing Data Accuracy = {self.testing_accuracy}\n"
            + f"Validation Data Accuracy = {self.validation_accuracy}\n"
            + "\n"
            + "MEAN ACCURACY PER BIN\n"
            + f"Training Data Mean Accuracy = {self.training_mean_acc_per_bin}\n"  # noqa: E501
            + f"Testing Data Mean Accuracy = {self.testing_mean_acc_per_bin}\n"
            + f"Validation Data Mean Accuracy = {self.validation_mean_acc_per_bin}\n"  # noqa: E501
            + "\n"
            + "MSE\n"
            + f"Training Data MSE = {self.training_MSE}\n"
            + f"Testing Data MSE = {self.testing_MSE}\n"
            + f"Validation Data MSE = {self.validation_MSE}\n"
        )
