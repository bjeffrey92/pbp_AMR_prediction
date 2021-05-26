import warnings
from typing import Tuple, Union

import numpy as np
import pandas as pd
import umap
from nptyping import NDArray
from scipy.sparse import csr_matrix
from scipy.spatial.distance import cdist
from sklearn.cluster import DBSCAN


class ClusteringPredictor:
    def __init__(
        self,
        clustering: DBSCAN,
        training_features: NDArray,
        training_labels: pd.Series,
        reducer: umap.UMAP = None,
    ):
        if reducer is not None:
            assert (
                reducer.n_components == training_features.shape[1]
            ), "If UMAP reducer is used the training features should \
be embedded"

        if len(clustering.core_sample_indices_) == 0:
            raise ValueError("Clustering is entirely noise")

        self.clustering = clustering
        self.training_features = training_features
        self.training_labels = training_labels
        self.core_sample_features = training_features[
            clustering.core_sample_indices_, :
        ]
        self.core_sample_labels = training_labels.iloc[
            clustering.core_sample_indices_
        ]
        self.reducer = reducer

    def predict(self, samples: Union[NDArray, csr_matrix]) -> NDArray:
        if isinstance(samples, csr_matrix):
            samples = samples.todense()

        if self.reducer is not None:
            samples = self.reducer.transform(samples)
            distances_to_core_samples = cdist(
                samples, self.core_sample_features, "euclidean"
            )
        else:
            distances_to_core_samples = cdist(
                samples, self.core_sample_features, "hamming"
            )
        predictions = self.core_sample_labels.iloc[
            np.argmin(distances_to_core_samples, axis=1)
        ]
        return predictions.values


def _fit_DBSCAN(
    train: Tuple[Union[csr_matrix, NDArray], NDArray],
    log_eps: float,
    min_samples: int,
) -> ClusteringPredictor:
    eps = 10 ** log_eps

    dense_features = train[0].todense()  # cant use hamming metric with sparse
    clustering = DBSCAN(
        eps=eps, min_samples=min_samples, metric="hamming", n_jobs=-1
    ).fit(dense_features)

    reg = ClusteringPredictor(clustering, dense_features, train[1])
    return reg


def _fit_DBSCAN_with_UMAP(
    train: Tuple[Union[csr_matrix, NDArray], NDArray],
    umap_components: Union[int, float],
    log_eps: float,
    min_samples: int,
) -> ClusteringPredictor:
    if isinstance(train[0], csr_matrix):
        features = train[0].todense()
    elif isinstance(train[0], NDArray):
        features = train[0]
    else:
        raise TypeError(
            "First element of train must be a numpy array or scipy CSR matrix"
        )

    eps = 10 ** log_eps
    umap_components = round(umap_components)

    reducer = umap.UMAP(
        metric="hamming", n_components=umap_components, n_jobs=-1
    )
    # reducer will display warning saying cannot do the reverse transform with
    # the hamming metric
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        embedding = reducer.fit_transform(features)

    clustering = DBSCAN(
        eps=eps, min_samples=min_samples, metric="euclidean", n_jobs=-1
    )
    clustering.fit(embedding)
    if len(clustering.core_sample_indices_) == 0:
        raise ValueError(
            f"Failed to identify any clusters in the data with eps={eps}, "
            + f"min_samples={min_samples}, "
            + f"and umap_components = {umap_components}"
        )

    reg = ClusteringPredictor(clustering, embedding, train[1], reducer)
    return reg
