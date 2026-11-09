"""Test helper: build a tiny, randomly-initialised Whisper model in CTranslate2
format plus a matching tokenizer.json, laid out like large-v3-turbo (51866
tokens, 128 mel bands), so the tests can run faster-whisper's real code paths
without downloading a model. Its output is gibberish by design.

    python tests/tiny_whisper.py OUT_DIR
"""
import json
import sys
from pathlib import Path

import numpy as np
from ctranslate2.specs import whisper_spec
from faster_whisper.tokenizer import _LANGUAGE_CODES
from tokenizers import Tokenizer, models, pre_tokenizers



def build(out: Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _build(out)
    return out


def _build(out: Path) -> None:
    rng = np.random.default_rng(0)
    D, HEADS, FFN, MELS = 64, 2, 256, 128

    # ---- vocabulary, exactly the large-v3 layout
    regular = [f"w{i}" for i in range(50257)]
    special = ["<|endoftext|>", "<|startoftranscript|>"] + [f"<|{c}|>" for c in _LANGUAGE_CODES]
    special += ["<|translate|>", "<|transcribe|>", "<|startoflm|>", "<|startofprev|>", "<|nospeech|>", "<|notimestamps|>"]
    timestamps = ["<|%.2f|>" % (i * 0.02) for i in range(1501)]
    tokens = regular + special + timestamps
    assert len(tokens) == 51866, len(tokens)
    VOCAB = len(tokens)


    def w(*shape):
        return (rng.standard_normal(shape) * 0.05).astype(np.float32)


    def ln(spec):
        spec.gamma = np.ones(D, np.float32)
        spec.beta = np.zeros(D, np.float32)


    def lin(spec, rows, cols, bias=True):
        spec.weight = w(rows, cols)
        if bias:
            spec.bias = np.zeros(rows, np.float32)


    spec = whisper_spec.WhisperSpec(1, HEADS, 1, HEADS)
    enc, dec = spec.encoder, spec.decoder
    enc.conv1.weight, enc.conv1.bias = w(D, MELS, 3), np.zeros(D, np.float32)
    enc.conv2.weight, enc.conv2.bias = w(D, D, 3), np.zeros(D, np.float32)
    enc.position_encodings.encodings = w(1500, D)
    ln(enc.layer_norm)
    for layer in enc.layer:
        ln(layer.self_attention.layer_norm)
        lin(layer.self_attention.linear[0], 3 * D, D)
        lin(layer.self_attention.linear[1], D, D)
        ln(layer.ffn.layer_norm)
        lin(layer.ffn.linear_0, FFN, D)
        lin(layer.ffn.linear_1, D, FFN)
    dec.embeddings.weight = w(VOCAB, D)
    dec.position_encodings.encodings = w(448, D)
    ln(dec.layer_norm)
    for layer in dec.layer:
        ln(layer.self_attention.layer_norm)
        lin(layer.self_attention.linear[0], 3 * D, D)
        lin(layer.self_attention.linear[1], D, D)
        ln(layer.attention.layer_norm)
        lin(layer.attention.linear[0], D, D)
        lin(layer.attention.linear[1], 2 * D, D)
        lin(layer.attention.linear[2], D, D)
        ln(layer.ffn.layer_norm)
        lin(layer.ffn.linear_0, FFN, D)
        lin(layer.ffn.linear_1, D, FFN)
    dec.projection.weight = w(VOCAB, D)

    eot = tokens.index("<|endoftext|>")
    spec.config.suppress_ids = []
    spec.config.suppress_ids_begin = [eot]
    spec.config.lang_ids = [tokens.index(f"<|{c}|>") for c in _LANGUAGE_CODES]
    spec.config.alignment_heads = [(0, 0), (0, 1)]
    spec.register_vocabulary(tokens)
    spec.validate()
    spec.save(str(out))

    # ---- tokenizer.json (word-level; enough for faster-whisper's lookups)
    tok = Tokenizer(models.WordLevel({t: i for i, t in enumerate(tokens)}, unk_token="w0"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.add_special_tokens(special + timestamps)
    tok.save(str(out / "tokenizer.json"))

    (out / "preprocessor_config.json").write_text(json.dumps({
        "feature_size": MELS, "sampling_rate": 16000, "hop_length": 160, "chunk_length": 30, "n_fft": 400,
    }))



if __name__ == "__main__":
    print("tiny model written to", build(Path(sys.argv[1])))
