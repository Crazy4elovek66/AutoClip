import pytest
from utils import sanitize_filename

def test_sanitize_filename_clean():
    # Test that a clean filename is unchanged
    assert sanitize_filename("video_123.mp4") == "video_123.mp4"

def test_sanitize_filename_dirty():
    # Test that invalid characters are replaced with underscore
    assert sanitize_filename("video:123/abc*xyz.mp4") == "video_123_abc_xyz.mp4"
    assert sanitize_filename("a\\b/c:d*e?f\"g<h>i|j") == "a_b_c_d_e_f_g_h_i_j"

def test_sanitize_filename_empty():
    # Test with empty string
    assert sanitize_filename("") == ""
