import argparse
import os
from copy import deepcopy
from typing import Any, Callable, List, Optional, Tuple, Union

import numpy as np

import speechset
from speechset.datasets import DataReader
from speechset.speeches.speechset import SpeechSet


class PairedDataset(SpeechSet):
    """Pairing the data w.r.t. the identifier.
    """
    def __init__(self, reader: DataReader, verbose: Optional[Callable] = None):
        """Cache the dataset and grouping the dataset with identifier.
        Args:
            reader: data reader.
            verbose: progressive bar verbose support, `tqdm` could be possible.
        """
        super().__init__(reader)
        self.groups = {}
        iters = self.dataset
        # verbose support
        if verbose:
            iters = verbose(iters)
        # group with sid
        for path in iters:
            # temp, hack of LibriTTS reader, for optimization
            key = os.path.basename(path).replace('.wav', '')
            sid, _ = self.reader.transcript[key]
            if sid not in self.groups:
                self.groups[sid] = []
            self.groups[sid].append(path)
        # set default pair
        self.random_pairing()

    def random_pairing(self, seed: Optional[int] = None):
        """Re-initialize the pair randomly.
        Args:
            seed: random seed.
        """
        rng = np.random.default_rng(seed)
        pairs = []
        for sid, paths in self.groups.items():
            indices = rng.permutation(len(paths))
            # repeating once
            if len(paths) % 2 == 1:
                indices = np.append(indices, indices[0])
            # pairing
            pairs.extend([
                (sid, paths[i], paths[j])
                for i, j in indices.reshape(-1, 2)])
        # set
        self.pairs = pairs

    def split(self, size: int):
        """Split dataset w.r.t. the speaker.
        Args:
            size: the number of the speakers for the first part.
        Returns:
            residual datset.
        """
        residual = deepcopy(self)
        groups = list(self.groups.items())
        # seperate the speaker groups
        residual.groups = dict(groups[size:])
        self.groups = dict(groups[:size])
        # random pairing
        residual.random_pairing()
        self.random_pairing()
        return residual

    def __getitem__(self, index: Union[int, slice]) -> Any:
        """Lazy normalizing.
        Args:
            index: input index.
        Returns:
            normalized inputs.
        """
        # reading pairs
        raw = self.pairs[index]
        if isinstance(index, int):
            # unpack
            sid, *paths = raw
            # preprocess
            p1, p2 = [self.normalize(*self.preproc(p)) for p in paths]
            return sid, p1, p2
        # normalize the slice
        bunches = [
            (sid, *[self.normalize(*self.preproc(p)) for p in paths])
            for sid, *paths in raw]
        return self.collate(bunches)

    def __len__(self) -> int:
        """Return length of the dataset.
        Returns:
            length.
        """
        return len(self.pairs)

    def normalize(self, sid: int, text: str, speech: np.ndarray) -> np.ndarray:
        """Normalize datum with auxiliary ids.
        Args:
            sid: speaker id.
            text: transcription.
            speech: [np.float32; [T]], speech in range (-1, 1).
        Returns:
            speech only (for augmentation)
        """
        return speech

    def collate(self, bunch: List[Tuple[int, np.ndarray, np.ndarray]]) \
            -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Collate bunch of datum to the batch data.
        Args:
            bunch: B x [...], list of normalized inputs.
                sid: speaker id.
                speech1, speech2: [np.float32; [T]], speach signal.
        Returns:
            batch data.
                sids: [np.long; [B]], speaker ids.
                lengths: [np.long; [B, 2]], speech lengths, 0 for speech1, 1 for speech2.
                speech1, speech2: [np.float32; [B, T]], speech signal.
        """
        # [B]
        sids = np.array([sid for sid, _, _ in bunch])
        # [B, 2]
        lengths = np.array([[len(s1), len(s2)] for _, s1, s2 in bunch])
        len1, len2 = lengths.max(axis=0)
        # [B, T]
        speech1 = np.stack([
            np.pad(signal, [0, len1 - len(signal)]) for _, signal, _ in bunch])
        speech2 = np.stack([
            np.pad(signal, [0, len2 - len(signal)]) for _, _, signal in bunch])
        return sids, lengths, speech1, speech2


class DumpedLibriTTS(speechset.utils.DumpDataset):
    """Dumped libritts support.
    """
    def __init__(self, data_dir: str):
        """Initializer.
        Args:
            data_dir: path to the dumped dataset.
        """
        super().__init__(DumpedLibriTTS.IDWrappedAcoustic, data_dir)

    class IDWrappedAcoustic(speechset.utils.IDWrapper):
        """ID-wrapper for DumpDataset support.
        """
        def __init__(self, *args, **kwargs):
            """Pass the acoustic dataset to the IDWrapper
            """
            super().__init__(speechset.AcousticDataset(*args, **kwargs))


def dump(data_dir: str,
         out_dir: str,
         num_proc: int,
         config: Optional[speechset.Config] = None) -> int:
    """Dump preprocessed LibriTTS datasets.
    Args:
        data_dir: dataset directory.
        out_dir: path to the dumped dataset.
        num_proc: the number of the processor.
        config: dataset configuration, if provided.
    Returns:
        dataset lengths.
    """
    config = config or speechset.Config()
    libri = speechset.datasets.LibriTTS(data_dir)
    # construct multi speaker
    acoustic = speechset.utils.IDWrapper(
        speechset.AcousticDataset(libri, config))
    # dump
    return speechset.utils.mp_dump(acoustic, out_dir, num_proc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default=None)
    parser.add_argument('--out-dir', default=None)
    parser.add_argument('--num-proc', defulat=4, type=int)
    args = parser.parse_args()

    dump(args.data_dir, args.out_dir, args.num_proc)