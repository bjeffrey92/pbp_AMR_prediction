from typing import Tuple, Union

import numpy as np
from nptyping import NDArray
from scipy.sparse import csr_matrix
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import ElasticNet, Lasso


def _fit_rf(
    train: Tuple[Union[csr_matrix, NDArray], NDArray], **kwargs
) -> RandomForestRegressor:
    kwargs = {k: round(v) for k, v in kwargs.items()}
    reg = RandomForestRegressor(**kwargs, n_jobs=-1)
    reg.fit(train[0], train[1])
    return reg


def _fit_en(
    train: Tuple[Union[csr_matrix, NDArray], NDArray],
    max_iter: int,
    l1_ratio: float = 0.5,
    alpha: float = 1.0,
) -> ElasticNet:
    reg = ElasticNet(
        alpha=alpha,
        l1_ratio=l1_ratio,
        random_state=0,
        max_iter=max_iter,
    )
    reg.fit(train[0], train[1])
    return reg


def _fit_lasso(
    train: Tuple[Union[csr_matrix, NDArray], NDArray],
    max_iter: int,
    alpha: float = 1.0,
) -> Lasso:
    reg = Lasso(alpha=alpha, random_state=0, max_iter=max_iter)
    reg.fit(train[0], train[1])
    return reg


def rf_prediction_distribution(
    data: Union[NDArray, csr_matrix],
    model: RandomForestRegressor,
) -> NDArray:
    return np.stack([tree.predict(data) for tree in model.estimators_], axis=1)


def rf_prediction_intervals(
    prediction_distribution: NDArray, PI: float = 0.95
) -> NDArray:
    """
    prediction_distribution should be generated by
    supervised_models.rf_prediction_distribution function
    """
    return np.quantile(prediction_distribution, (1 - PI, PI), 1).transpose()


def rf_PI_accuracy(labels: NDArray, prediction_intervals: NDArray) -> NDArray:
    """
    prediction_intervals should be generated by
    supervised_models.rf_prediction_intervals
    """
    return (
        np.logical_and(
            prediction_intervals[:, 0] <= labels,
            prediction_intervals[:, 1] >= labels,
        ).sum()
        / len(labels)
        * 100
    )
