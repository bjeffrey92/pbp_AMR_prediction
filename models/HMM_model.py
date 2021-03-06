from functools import lru_cache
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd
import pyhmmer
from nptyping import NDArray
from pyhmmer.plan7 import HMM


class ProfileHMMPredictor:
    def __init__(
        self,
        training_data: pd.DataFrame,
        pbp_seqs: List[str] = ["a1_seq", "b2_seq", "x2_seq"],
        drop_duplicates_for_training: bool = True,
        HMM_per_phenotype: bool = True,
        null_model_uniform_frequencies: bool = True,
    ):
        self.pbp_seqs = pbp_seqs
        self.alphabet = pyhmmer.easel.Alphabet.amino()
        self.background = pyhmmer.plan7.Background(
            self.alphabet, uniform=null_model_uniform_frequencies
        )
        self.builder = pyhmmer.plan7.Builder(self.alphabet)
        self.pipeline = pyhmmer.plan7.Pipeline(
            self.alphabet, background=self.background
        )
        if HMM_per_phenotype:
            self.hmm_mic_dict = self._phenotype_representative_HMMs(
                training_data, drop_duplicates_for_training
            )
            self.hmm = None
        else:
            self.hmm = self._build_hmm(
                training_data[pbp_seqs].sum(axis=1), 1.0
            )
            self.hmm_mic_dict = None  # type: ignore

    def _build_hmm(self, sequences: Iterable[str], mic: float) -> HMM:
        seqs = [
            pyhmmer.easel.TextSequence(name=str(i).encode(), sequence=j)
            for i, j in enumerate(sequences)
        ]
        msa = pyhmmer.easel.TextMSA(
            name=str(mic).encode(), sequences=seqs
        ).digitize(self.alphabet)
        return self.builder.build_msa(msa, self.background)[0]

    def _phenotype_representative_HMMs(
        self,
        data: pd.DataFrame,
        unique_sequences: bool = True,
    ) -> Dict:
        data.loc[:, "log2_mic"] = data.log2_mic.apply(round)
        data.sort_values(by="log2_mic", inplace=True)
        hmm_mic_dict = {}  # type: ignore
        for mic, sequences in data.groupby("log2_mic"):
            sequences = sequences[self.pbp_seqs].sum(axis=1)
            if unique_sequences:
                sequences.drop_duplicates(inplace=True)
            hmm_mic_dict[mic] = self._build_hmm(sequences, mic)
        return hmm_mic_dict

    def _get_HMM_hits(self, seqs: Iterable[str]) -> List:
        @lru_cache(maxsize=None)
        def get_hits(seq):
            seq = pyhmmer.easel.TextSequence(sequence=seq).digitize(
                self.alphabet
            )
            hits = self.pipeline.scan_seq(seq, self.hmm_mic_dict.values())
            return sorted(hits, key=lambda x: x.score, reverse=True)[0]

        return [get_hits(seq) for seq in seqs]

    def predict_phenotype(self, seqs: Iterable[str]) -> NDArray:
        sequence_hits = self._get_HMM_hits(seqs)
        return np.array([float(hit.name) for hit in sequence_hits])

    def closest_HMM(self, seqs: Iterable[str]) -> List[str]:
        sequence_hits = self._get_HMM_hits(seqs)
        return [self.hmm_mic_dict[float(hit.name)] for hit in sequence_hits]

    def all_HMM_scores(self, seqs: Iterable[str]) -> NDArray:
        """
        Either returns one score for the HMM trained on the whole dataset or
        one per HMM in self.hmm_mic_dict
        """

        @lru_cache(maxsize=None)
        def get_hmm_scores(seq):
            seq = pyhmmer.easel.TextSequence(sequence=seq).digitize(
                self.alphabet
            )
            if self.hmm_mic_dict is not None:
                hits = self.pipeline.scan_seq(seq, self.hmm_mic_dict.values())
                return np.array([hit.score for hit in hits])
            else:
                hit = self.pipeline.search_hmm(self.hmm, [seq])[0]
                return hit.score

        return np.array([get_hmm_scores(seq) for seq in seqs])


def get_HMM_scores(hmm_predictor: ProfileHMMPredictor, pbps: List[str], *args):
    sequences = [data[pbps].sum(axis=1) for data in args]
    return [hmm_predictor.all_HMM_scores(seqs) for seqs in sequences]
