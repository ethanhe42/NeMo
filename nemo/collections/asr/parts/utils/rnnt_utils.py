# Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Copyright 2017 Johns Hopkins University (Shinji Watanabe)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import torch


@dataclass
class Hypothesis:
    """Hypothesis class for beam search algorithms.

    score: A float score obtained from an AbstractRNNTDecoder module's score_hypothesis method.

    y_sequence: Either a sequence of integer ids pointing to some vocabulary, or a packed torch.Tensor
        behaving in the same manner. dtype must be torch.Long in the latter case.

    dec_state: A list (or list of list) of LSTM-RNN decoder states. Can be None.

    text: (Optional) A decoded string after processing via CTC / RNN-T decoding (removing the CTC/RNNT
        `blank` tokens, and optionally merging word-pieces). Should be used as decoded string for
        Word Error Rate calculation.

    timestep: (Optional) A list of integer indices representing at which index in the decoding
        process did the token appear. Should be of same length as the number of non-blank tokens.

    alignments: (Optional) Represents the CTC / RNNT token alignments as integer tokens along an axis of
        time T (for CTC) or Time x Target (TxU).
        For CTC, represented as a single list of integer indices.
        For RNNT, represented as a dangling list of list of integer indices.
        Outer list represents Time dimension (T), inner list represents Target dimension (U).
        The set of valid indices **includes** the CTC / RNNT blank token in order to represent alignments.

    frame_confidence: (Optional) Represents the CTC / RNNT per-frame confidence scores as token probabilities
        along an axis of time T (for CTC) or Time x Target (TxU).
        For CTC, represented as a single list of float indices.
        For RNNT, represented as a dangling list of list of float indices.
        Outer list represents Time dimension (T), inner list represents Target dimension (U).

    token_confidence: (Optional) Represents the CTC / RNNT per-token confidence scores as token probabilities
        along an axis of Target U.
        Represented as a single list of float indices.

    word_confidence: (Optional) Represents the CTC / RNNT per-word confidence scores as token probabilities
        along an axis of Target U.
        Represented as a single list of float indices.

    length: Represents the length of the sequence (the original length without padding), otherwise
        defaults to 0.

    y: (Unused) A list of torch.Tensors representing the list of hypotheses.

    lm_state: (Unused) A dictionary state cache used by an external Language Model.

    lm_scores: (Unused) Score of the external Language Model.

    ngram_lm_state: (Optional) State of the external n-gram Language Model.

    tokens: (Optional) A list of decoded tokens (can be characters or word-pieces.

    last_token (Optional): A token or batch of tokens which was predicted in the last step.
    """

    score: float
    y_sequence: Union[List[int], torch.Tensor]
    text: Optional[str] = None
    dec_out: Optional[List[torch.Tensor]] = None
    dec_state: Optional[Union[List[List[torch.Tensor]], List[torch.Tensor]]] = None
    timestep: Union[List[int], torch.Tensor] = field(default_factory=list)
    alignments: Optional[Union[List[int], List[List[int]]]] = None
    frame_confidence: Optional[Union[List[float], List[List[float]]]] = None
    token_confidence: Optional[List[float]] = None
    word_confidence: Optional[List[float]] = None
    length: Union[int, torch.Tensor] = 0
    y: List[torch.tensor] = None
    lm_state: Optional[Union[Dict[str, Any], List[Any]]] = None
    lm_scores: Optional[torch.Tensor] = None
    ngram_lm_state: Optional[Union[Dict[str, Any], List[Any]]] = None
    tokens: Optional[Union[List[int], torch.Tensor]] = None
    last_token: Optional[torch.Tensor] = None

    @property
    def non_blank_frame_confidence(self) -> List[float]:
        """Get per-frame confidence for non-blank tokens according to self.timestep

        Returns:
            List with confidence scores. The length of the list is the same as `timestep`.
        """
        non_blank_frame_confidence = []
        # self.timestep can be a dict for RNNT
        timestep = self.timestep['timestep'] if isinstance(self.timestep, dict) else self.timestep
        if len(self.timestep) != 0 and self.frame_confidence is not None:
            if any(isinstance(i, list) for i in self.frame_confidence):  # rnnt
                t_prev = -1
                offset = 0
                for t in timestep:
                    if t != t_prev:
                        t_prev = t
                        offset = 0
                    else:
                        offset += 1
                    non_blank_frame_confidence.append(self.frame_confidence[t][offset])
            else:  # ctc
                non_blank_frame_confidence = [self.frame_confidence[t] for t in timestep]
        return non_blank_frame_confidence

    @property
    def words(self) -> List[str]:
        """Get words from self.text

        Returns:
            List with words (str).
        """
        return [] if self.text is None else self.text.split()


@dataclass
class NBestHypotheses:
    """List of N best hypotheses"""

    n_best_hypotheses: Optional[List[Hypothesis]]


@dataclass
class HATJointOutput:
    """HATJoint outputs for beam search decoding

    hat_logprobs: standard HATJoint outputs as for RNNTJoint

    ilm_logprobs: internal language model probabilities (for ILM subtraction)
    """

    hat_logprobs: Optional[torch.Tensor] = None
    ilm_logprobs: Optional[torch.Tensor] = None


def is_prefix(x: List[int], pref: List[int]) -> bool:
    """
    Obtained from https://github.com/espnet/espnet.

    Check if pref is a prefix of x.

    Args:
        x: Label ID sequence.
        pref: Prefix label ID sequence.

    Returns:
        : Whether pref is a prefix of x.
    """
    if len(pref) >= len(x):
        return False

    for i in range(len(pref)):
        if pref[i] != x[i]:
            return False

    return True


def select_k_expansions(
    hyps: List[Hypothesis], topk_idxs: torch.Tensor, topk_logps: torch.Tensor, gamma: float, beta: int,
) -> List[Tuple[int, Hypothesis]]:
    """
    Obtained from https://github.com/espnet/espnet

    Return K hypotheses candidates for expansion from a list of hypothesis.
    K candidates are selected according to the extended hypotheses probabilities
    and a prune-by-value method. Where K is equal to beam_size + beta.

    Args:
        hyps: Hypotheses.
        topk_idxs: Indices of candidates hypothesis. Shape = [B, num_candidates]
        topk_logps: Log-probabilities for hypotheses expansions. Shape = [B, V + 1]
        gamma: Allowed logp difference for prune-by-value method.
        beta: Number of additional candidates to store.

    Return:
        k_expansions: Best K expansion hypotheses candidates.
    """
    k_expansions = []

    for i, hyp in enumerate(hyps):
        hyp_i = [(int(k), hyp.score + float(v)) for k, v in zip(topk_idxs[i], topk_logps[i])]
        k_best_exp_val = max(hyp_i, key=lambda x: x[1])

        k_best_exp_idx = k_best_exp_val[0]
        k_best_exp = k_best_exp_val[1]

        expansions = sorted(filter(lambda x: (k_best_exp - gamma) <= x[1], hyp_i), key=lambda x: x[1],)

        if len(expansions) > 0:
            k_expansions.append(expansions)
        else:
            k_expansions.append([(k_best_exp_idx, k_best_exp)])

    return k_expansions


class BatchedHyps:
    """Class to store batched hypotheses (labels, time_indices, scores) for efficient RNNT decoding"""

    def __init__(
        self,
        batch_size: int,
        init_length: int,
        device: Optional[torch.device] = None,
        float_dtype: Optional[torch.dtype] = None,
    ):
        if init_length <= 0:
            raise ValueError(f"init_length must be > 0, got {init_length}")
        if batch_size <= 0:
            raise ValueError(f"batch_size must be > 0, got {batch_size}")
        self._max_length = init_length
        self.lengths = torch.zeros(batch_size, device=device, dtype=torch.long)
        self.transcript = torch.zeros((batch_size, self._max_length), device=device, dtype=torch.long)
        self.timesteps = torch.zeros((batch_size, self._max_length), device=device, dtype=torch.long)
        self.scores = torch.zeros(batch_size, device=device, dtype=float_dtype)
        # tracking last timestep of each hyp to avoid infinite looping (when max symbols per frame is restricted)
        self.last_timestep_lasts = torch.zeros(batch_size, device=device, dtype=torch.long)
        self.last_timestep = torch.full((batch_size,), -1, device=device, dtype=torch.long)

    def _allocate_more(self):
        """
        Allocate 2x space for tensors, similar to common C++ std::vector implementations
        to maintain O(1) insertion time complexity
        """
        self.transcript = torch.cat((self.transcript, torch.zeros_like(self.transcript)), dim=-1)
        self.timesteps = torch.cat((self.timesteps, torch.zeros_like(self.timesteps)), dim=-1)
        self._max_length *= 2

    def add_results_(
        self, active_indices: torch.Tensor, labels: torch.Tensor, time_indices: torch.Tensor, scores: torch.Tensor
    ):
        """
        Add results (inplace) from a decoding step to the batched hypotheses
        Args:
            active_indices: tensor with indices of active hypotheses (indices should be within the original batch_size)
            labels: non-blank labels to add
            time_indices: tensor of time index for each label
            scores: label scores
        """
        # we assume that all tensors have the same first dimension, and labels are non-blanks
        if active_indices.shape[0] == 0:
            return  # nothing to add
        if self.lengths.max().item() >= self._max_length:
            self._allocate_more()
        self.scores[active_indices] += scores
        indices_to_use = active_indices * self._max_length + self.lengths[active_indices]
        self.transcript.view(-1)[indices_to_use] = labels
        self.timesteps.view(-1)[indices_to_use] = time_indices
        self.last_timestep_lasts[active_indices] = torch.where(
            self.last_timestep[active_indices] == time_indices, self.last_timestep_lasts[active_indices] + 1, 1
        )
        self.last_timestep[active_indices] = time_indices
        self.lengths[active_indices] += 1


class BatchedAlignments:
    """
    Class to store batched alignments (logits, labels, frame_confidence).
    Size is different from hypotheses, since blank outputs are preserved
    """

    def __init__(
        self,
        batch_size: int,
        logits_dim: int,
        init_length: int,
        device: Optional[torch.device] = None,
        float_dtype: Optional[torch.dtype] = None,
        with_frame_confidence: bool = False,
    ):
        if init_length <= 0:
            raise ValueError(f"init_length must be > 0, got {init_length}")
        if batch_size <= 0:
            raise ValueError(f"batch_size must be > 0, got {batch_size}")
        self.with_frame_confidence = with_frame_confidence
        self._max_length = init_length
        self.logits = torch.zeros((batch_size, self._max_length, logits_dim), device=device, dtype=float_dtype)
        self.labels = torch.zeros((batch_size, self._max_length), device=device, dtype=torch.long)
        self.lengths = torch.zeros(batch_size, device=device, dtype=torch.long)
        if self.with_frame_confidence:
            self.frame_confidence = torch.zeros((batch_size, self._max_length), device=device, dtype=torch.long)
        else:
            self.frame_confidence = None

    def _allocate_more(self):
        """
        Allocate 2x space for tensors, similar to common C++ std::vector implementations
        to maintain O(1) insertion time complexity
        """
        self.logits = torch.cat((self.logits, torch.zeros_like(self.logits)), dim=-1)
        self.labels = torch.cat((self.labels, torch.zeros_like(self.labels)), dim=-1)
        if self.with_frame_confidence:
            self.frame_confidence = torch.cat((self.frame_confidence, torch.zeros_like(self.frame_confidence)), dim=-1)
        self._max_length *= 2

    def add_results_(
        self,
        active_indices: torch.Tensor,
        logits: torch.Tensor,
        labels: torch.Tensor,
        confidence: Optional[torch.Tensor] = None,
    ):
        """
        Add results (inplace) from a decoding step to the batched hypotheses
        Args:
            active_indices: tensor with indices of active hypotheses (indices should be within the original batch_size)
            logits: tensor with raw network outputs
            labels: tensor with decoded labels (can contain blank)
            confidence: optional tensor with confidence for each item in batch
        """
        # we assume that all tensors have the same first dimension
        if active_indices.shape[0] == 0:
            return  # nothing to add
        if self.lengths.max().item() >= self._max_length:
            self._allocate_more()
        logits_dim = self.logits.shape[-1]
        indices_to_use = active_indices * self._max_length + self.lengths[active_indices]
        self.logits.view(-1, logits_dim)[indices_to_use] = logits
        self.labels.view(-1)[indices_to_use] = labels
        if self.with_frame_confidence and confidence is not None:
            self.frame_confidence.view(-1)[indices_to_use] = confidence
        self.lengths[active_indices] += 1


def batched_hyps_to_hypotheses(
    batched_hyps: BatchedHyps, alignments: Optional[BatchedAlignments] = None
) -> List[Hypothesis]:
    """
    Convert batched hypotheses to a list of Hypothesis objects.
    Keep this funcion separate to allow for jit compilation for BatchedHyps class (see tests)

    Args:
        batched_hyps: BatchedHyps object

    Returns:
        list of Hypothesis objects
    """
    alignment_lengths = None
    alignment_labels = None
    frame_confidence = None
    alignment_logits = None
    if alignments is not None:
        # move to CPU all tensors before saving to hypotheses
        alignment_lengths = alignments.lengths.cpu().tolist()
        alignment_labels = alignments.labels.cpu()
        alignment_logits = alignments.logits.cpu()
        if alignments.with_frame_confidence:
            frame_confidence = alignments.frame_confidence.cpu()
    hypotheses = [
        Hypothesis(
            score=batched_hyps.scores[i].item(),
            y_sequence=batched_hyps.transcript[i, : batched_hyps.lengths[i]],
            timestep=batched_hyps.timesteps[i, : batched_hyps.lengths[i]],
            alignments=[
                (alignment_labels[i, time_i], alignment_logits[i, time_i]) for time_i in range(alignment_lengths[i])
            ]
            if alignment_lengths is not None
            else None,
            frame_confidence=[frame_confidence[i, : alignment_lengths[i]].tolist()]
            if frame_confidence is not None
            else None,
            dec_state=None,
        )
        for i in range(batched_hyps.scores.shape[0])
    ]
    return hypotheses
