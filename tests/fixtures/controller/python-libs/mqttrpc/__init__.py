__version = (0, 1, 0)

__version__ = version = ".".join(map(str, __version))  # pylint: disable=invalid-name
__project__ = PROJECT = __name__

from .dispatcher import Dispatcher  # pylint: disable=wrong-import-position
from .manager import MQTTRPCResponseManager  # pylint: disable=wrong-import-position

dispatcher = Dispatcher()

# lint_ignore=W0611,W0401
