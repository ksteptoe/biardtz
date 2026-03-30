# ---- Python API ----
# The functions defined in this section can be imported by users in their
# Python scripts/interactive interpreter, e.g. via
# `from my_test_project.biardz import biardz`,
# when using this Python module as a library.

import logging
import sys
from biardz import __version__

_logger = logging.getLogger(__name__)


def setup_logging(loglevel):
    """Setup basic logging

    Args:
      loglevel (int): minimum loglevel for emitting messages
    """
    logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
    )


def biardz_api(loglevel: int ):
    """Wrapper allowing :func: $(package) to be called with string arguments in a CLI fashion

    Args:
      loglevel: int
    """
    setup_logging(loglevel)
    _logger.info(f"Version: {__version__}")
    # Code Here
    _logger.info("Script ends here")


