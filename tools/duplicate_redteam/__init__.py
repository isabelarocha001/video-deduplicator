"""
Internal QA / Adversarial Testing Laboratory for media deduplication.

This tool generates perceptual variants of known media and evaluates whether
the detection pipeline correctly identifies them as duplicates (same content).

IMPORTANT:
- Internal development / QA use only.
- Not intended for production, public APIs, or bypassing platform detection.
- Goal: discover FALSE NEGATIVES to strengthen the real detector.
"""

__version__ = "0.1.0"
