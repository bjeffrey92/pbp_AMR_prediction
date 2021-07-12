import pickle
from multiprocessing import cpu_count
from typing import Iterable

import matplotlib.pyplot as plt
import numpyro
from jax import numpy as jnp
from jax import random
from jax.interpreters.xla import _DeviceArray
from numpyro import sample
from numpyro.distributions import (
    ImproperUniform,
    Normal,
    OrderedLogistic,
    constraints,
)
from numpyro.infer import MCMC, NUTS, Predictive
import seaborn as sns

# this has to be set before calling any other numpyro functions
numpyro.set_host_device_count(cpu_count())


class BayesianOrdinalRegression:
    def __init__(
        self,
        X: Iterable,
        Y: Iterable,
        X_dim: int,
        n_classes: int,
        beta_prior_sd: float = 1.0,
        num_chains: int = 4,
    ):
        if not isinstance(X, _DeviceArray):
            X = jnp.array(X)
        if not isinstance(Y, _DeviceArray):
            Y = jnp.array(Y)
        self.X = X
        self.Y = Y
        self.X_dim = X_dim
        self.n_classes = n_classes
        self.beta_prior_sd = beta_prior_sd
        self.mcmc_key = random.PRNGKey(1234)
        self.num_chains = num_chains
        self.posterior_samples = None
        self.mcmc_last_state = None

    def _model(self, X, Y=None):
        b_X_eta = sample(
            "b_X_eta", Normal(0, jnp.array([self.beta_prior_sd] * self.X_dim))
        )  # betas for each X are drawn from normal distribution
        c_y = sample(
            "c_y",
            ImproperUniform(
                support=constraints.ordered_vector,
                batch_shape=(),
                event_shape=(self.n_classes - 1,),
            ),
        )  # cutpoints for ordered logisitic model
        with numpyro.plate("obs", X.shape[0]):
            eta = X * b_X_eta
            eta = eta.sum(axis=1)  # summing across beta coefficients
            return sample("Y", OrderedLogistic(eta, c_y), obs=Y)

    def fit(
        self,
        num_warmup: int = 2500,
        num_samples: int = 7500,
    ):
        kernel = NUTS(self._model)

        if self.mcmc_last_state is None:
            self.mcmc = MCMC(
                kernel,
                num_warmup=num_warmup,
                num_samples=num_samples,
                num_chains=self.num_chains,
                jit_model_args=True,
            )
        else:
            if num_warmup != 0:
                print(
                    "Starting sampling from previously saved state, ignoring num_warmup argument"  # noqa: E501
                )
            self.mcmc = MCMC(
                kernel,
                num_warmup=0,
                num_samples=num_samples,
                num_chains=self.num_chains,
                jit_model_args=True,
            )

        if self.mcmc_last_state is None:
            self.mcmc.run(self.mcmc_key, self.X, self.Y)
        else:
            self.mcmc.run(self.mcmc_last_state.rng_key, self.X, self.Y)

        self.mcmc_last_state = self.mcmc.last_state  # store final state

        if self.posterior_samples is None:
            self.posterior_samples = self.mcmc.get_samples()
        else:
            self.posterior_samples = {
                k: jnp.concatenate(
                    [v, self.mcmc.get_samples()[k]],
                    axis=0,
                )
                for k, v in self.posterior_samples.items()
            }

    def predict(self, X: Iterable) -> _DeviceArray:
        if not isinstance(X, _DeviceArray):
            X = jnp.array(X)
        return Predictive(
            self._model,
            posterior_samples=self.posterior_samples,
            parallel=True,
        )(self.mcmc_key, X)["Y"]

    def plot_posteriors(self, n: int, param_type: str):
        param_name = f"{param_type}_{n}"
        param_chains = self.posterior_samples[param_type][:, n]  # type: ignore # noqa: E501
        param_chains = jnp.array_split(param_chains, self.num_chains)
        plt.clf()
        for n, chain in enumerate(param_chains):
            n += 1
            mean = jnp.mean(chain)
            median = jnp.median(chain)
            CI_lower = jnp.percentile(chain, 2.5)
            CI_upper = jnp.percentile(chain, 97.5)

            # trace plot
            plt.subplot(4, 2, (n * 2) - 1)
            plt.plot(chain)
            plt.axhline(mean, color="r", lw=2, linestyle="--")
            plt.axhline(median, color="c", lw=2, linestyle="--")
            plt.axhline(CI_lower, linestyle=":", color="k", alpha=0.2)
            plt.axhline(CI_upper, linestyle=":", color="k", alpha=0.2)

            # density plot
            plt.subplot(4, 2, n * 2)
            plt.hist(chain, 30, density=True)
            sns.kdeplot(chain, shade=True)
            plt.ylabel("")
            plt.axvline(mean, color="r", lw=2, linestyle="--", label="mean")
            plt.axvline(
                median, color="c", lw=2, linestyle="--", label="median"
            )
            plt.axvline(
                CI_lower, linestyle=":", color="k", alpha=0.2, label="95% CI"
            )
            plt.axvline(CI_upper, linestyle=":", color="k", alpha=0.2)

        plt.suptitle(f"Trace and Posterior Distribution for {param_name}")
        plt.gcf().tight_layout()
        plt.legend(loc="lower right")
        plt.show()

        plt.clf()


def save_bayesian_ordinal_regression(
    model: BayesianOrdinalRegression, filename: str
):
    attributes_dict = {
        "X": model.X,
        "Y": model.Y,
        "X_dim": model.X_dim,
        "n_classes": model.n_classes,
        "beta_prior_sd": model.beta_prior_sd,
        "mcmc_key": model.mcmc_key,
        "posterior_samples": model.posterior_samples,
        "mcmc_last_state": model.mcmc_last_state,
        "num_chains": model.num_chains,
    }
    with open(filename, "wb") as a:
        pickle.dump(attributes_dict, a)


def load_bayesian_ordinal_regression(
    filename: str,
) -> BayesianOrdinalRegression:
    with open(filename, "rb") as a:
        attributes_dict = pickle.load(a)

    model = BayesianOrdinalRegression(
        attributes_dict["X"],
        attributes_dict["Y"],
        attributes_dict["X_dim"],
        attributes_dict["n_classes"],
        attributes_dict["beta_prior_sd"],
        attributes_dict["num_chains"],
    )
    model.mcmc_key = attributes_dict["mcmc_key"]
    model.posterior_samples = attributes_dict["posterior_samples"]
    model.mcmc_last_state = attributes_dict["mcmc_last_state"]

    return model
