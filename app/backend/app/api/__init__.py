"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
models_bp = Blueprint('models', __name__)
world_bp = Blueprint('world', __name__)
timeline_bp = Blueprint('timeline', __name__)
assistant_bp = Blueprint('assistant', __name__)
support_bp = Blueprint('support', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import models  # noqa: E402, F401
from . import world  # noqa: E402, F401
from . import timeline  # noqa: E402, F401
from . import assistant  # noqa: E402, F401
from . import support  # noqa: E402, F401
