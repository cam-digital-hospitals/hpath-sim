"""The simulation server.

REST API
--------

..
  #pylint: disable=line-too-long

+---------------------------------------+-----------------+------------------------------------------------------+
| **Endpoint**                          | **HTTP Method** | **Python function signature**                        |
+=======================================+=================+======================================================+
| ``/``                                 | GET             | :py:func:`~hpath.restful.server.hello_world()`       |
+                                       +-----------------+------------------------------------------------------+
|                                       | DELETE          | :py:func:`~hpath.restful.server.reset()`             |
+---------------------------------------+-----------------+------------------------------------------------------+
| ``/scenarios/``                       | POST            | :py:func:`~hpath.restful.server.new_scenario_rest`   |
|                                       +-----------------+------------------------------------------------------+
|                                       | GET             | :py:func:`~hpath.restful.server.list_scenarios_rest` |
+---------------------------------------+-----------------+------------------------------------------------------+
| ``/scenarios/<scenario_id>/status/``  | GET             | :py:func:`~hpath.restful.server.status_rest`         |
+---------------------------------------+-----------------+------------------------------------------------------+
| ``/scenarios/<scenario_id>/results/`` | GET             | :py:func:`~hpath.restful.server.results_rest`        |
+---------------------------------------+-----------------+------------------------------------------------------+
| ``/multi/``                           | POST            | :py:func:`~hpath.restful.server.new_multi_rest`      |
|                                       +-----------------+------------------------------------------------------+
|                                       | GET             | :py:func:`~hpath.restful.server.list_multis_rest`    |
+---------------------------------------+-----------------+------------------------------------------------------+
| ``/multi/<analysis_id>/status/``      | GET             | :py:func:`~hpath.restful.server.status_multi_rest`   |
+---------------------------------------+-----------------+------------------------------------------------------+
| ``/multi/<analysis_id>/results/``     | GET             | :py:func:`~hpath.restful.server.results_multi_rest`  |
+---------------------------------------+-----------------+------------------------------------------------------+

..
  #pylint: enable=line-too-long
"""

from base64 import b64decode
from io import BytesIO
import json
from http import HTTPStatus

from flask import Flask, Response, request
from werkzeug.exceptions import HTTPException

import pandas as pd
import openpyxl as oxl

from conf import PORT
from hpath_backend.simulate import simulate
from .. import db
from ..config import Config
from ..types import HPathConfigParams, HPathSharedParams
from .job_queue import HPATH_SIM_QUEUE

app = Flask(__name__)


@app.errorhandler(HTTPException)
def handle_exception(exc: HTTPException):
    """Return JSON instead of HTML (the default) for HTTP errors."""
    # start with the correct headers and status code from the error
    response = exc.get_response()
    # replace the body with JSON
    response.data = json.dumps({
        "code": exc.code,
        "name": exc.name,
        "description": exc.description,
    }, separators=(',', ':'))
    response.content_type = "application/json"
    return response

########################################################################################
##                                                                                    ##
##  ######## ##    ## ########  ########   #######  #### ##    ## ########  ######    ##
##  ##       ###   ## ##     ## ##     ## ##     ##  ##  ###   ##    ##    ##    ##   ##
##  ##       ####  ## ##     ## ##     ## ##     ##  ##  ####  ##    ##    ##         ##
##  ######   ## ## ## ##     ## ########  ##     ##  ##  ## ## ##    ##     ######    ##
##  ##       ##  #### ##     ## ##        ##     ##  ##  ##  ####    ##          ##   ##
##  ##       ##   ### ##     ## ##        ##     ##  ##  ##   ###    ##    ##    ##   ##
##  ######## ##    ## ########  ##         #######  #### ##    ##    ##     ######    ##
##                                                                                    ##
########################################################################################

# See: https://flask.palletsprojects.com/en/3.0.x/quickstart/#about-responses


@app.route('/')
def hello_world() -> Response:
    """Return a simple HTML message, unless the request body is 'PING' (returns 'PONG' instead.)"""
    if request.get_data(as_text=True) == 'PING':
        return Response('PONG', status=HTTPStatus.OK, mimetype='text/plain')
    return "<h1>Hello World!</h1>"


@app.route('/submit/', methods=['POST'])
def new_scenario_rest() -> Response:
    """Process POST request for creating a new scenario or multi-scenario analysis."""
    sc_data: dict = request.json['scenarios']
    params_dict: dict = request.json['params']

    try:
        params = HPathSharedParams(**params_dict)
        configs = parse_sc_data(sc_data, params)
    except Exception as exc:  # Parse error
        return {'type': type(exc), 'msg': str(exc)}, HTTPStatus.BAD_REQUEST

    try:
        scenario_ids = db.submit_scenarios(configs, params)
    except Exception as exc:  # Database error
        return {'type': type(exc), 'msg': str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE

    try:
        for config, scenario_id in zip(configs, scenario_ids):
            config_obj = Config(**json.loads(config.config))
            HPATH_SIM_QUEUE.enqueue(simulate, config_obj, scenario_id)
    except Exception as exc:  # Redis error
        return {'type': type(exc), 'msg': str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE

    return Response(status=HTTPStatus.OK)


@app.route('/scenarios/')
def list_scenarios_rest() -> Response:
    """Return a dict of scenarios on the server. Used to populate a Dash AG Grid."""
    scenarios = db.list_scenarios()
    return scenarios


# TODO remaining endpoints

######################################################################################
##                                                                                  ##
##  ##     ## ######## ##       ########  ######## ########                         ##
##  ##     ## ##       ##       ##     ## ##       ##     ##                        ##
##  ##     ## ##       ##       ##     ## ##       ##     ##                        ##
##  ######### ######   ##       ########  ######   ########                         ##
##  ##     ## ##       ##       ##        ##       ##   ##                          ##
##  ##     ## ##       ##       ##        ##       ##    ##                         ##
##  ##     ## ######## ######## ##        ######## ##     ##                        ##
##                                                                                  ##
##  ######## ##     ## ##    ##  ######  ######## ####  #######  ##    ##  ######   ##
##  ##       ##     ## ###   ## ##    ##    ##     ##  ##     ## ###   ## ##    ##  ##
##  ##       ##     ## ####  ## ##          ##     ##  ##     ## ####  ## ##        ##
##  ######   ##     ## ## ## ## ##          ##     ##  ##     ## ## ## ##  ######   ##
##  ##       ##     ## ##  #### ##          ##     ##  ##     ## ##  ####       ##  ##
##  ##       ##     ## ##   ### ##    ##    ##     ##  ##     ## ##   ### ##    ##  ##
##  ##        #######  ##    ##  ######     ##    ####  #######  ##    ##  ######   ##
##                                                                                  ##
######################################################################################

class ExcelException(Exception):
    """Raised when openpyxl raises an error."""


class ParseConfigError(Exception):
    """Raised when parsing an openpyxl Workbook as a Config raises an error."""


def parse_sc_data(sc_data: dict, params: HPathSharedParams) -> list[HPathConfigParams]:
    """Parse and validate scenario data from REST request."""

    sc_df = pd.DataFrame(sc_data)
    configs: list[HPathConfigParams] = []

    # LOAD AND PARSE EACH SCENARIO
    for sc in sc_df.itertuples():
        app.logger.info("%s. %s %s %s", sc.Index, sc.sc_name, sc.file_name, sc.decode_len_str)
        sc_bytes = b64decode(sc.file_base64.split('base64,')[1])

        # Try to load the xlsx file in openpyxl
        try:
            # data_only: Replace formulas with computed values
            wbook = oxl.load_workbook(BytesIO(sc_bytes), data_only=True)
        except Exception as exc:
            app.logger.error(
                'Error when reading "%s" (scenario "%s"): %s',
                sc.file_name, sc.sc_name, str(exc)
            )
            raise ExcelException(
                f"""\
Error when reading {sc.file_name} (scenario {sc.sc_name}). \
Is the file a valid Excel file?

openpyxl error message:
    {str(exc)}
"""
            ) from exc

        # Validate the config
        try:
            config = Config.from_workbook(wbook, params.sim_hours, params.num_reps)
            config_data = HPathConfigParams(
                name=sc.sc_name,
                file_name=sc.file_name,
                config=config.model_dump_json(),
                file=sc_bytes
            )
            configs.append(config_data)
        except Exception as exc:
            app.logger.error(
                '    Error (type %s) when parsing "%s" (scenario "%s"): %s',
                type(exc), sc.file_name, sc.sc_name, str(exc)
            )
            raise ParseConfigError(
                f"""\
Error (type {type(exc)}) when parsing “{sc.file_name}” (scenario: “{sc.sc_name}”): \
    {str(exc)}
"""
            ) from exc

        app.logger.info('OK!')

    app.logger.info('')
    app.logger.info('')

    return configs

##########################################
##                                      ##
##  ##     ##    ###    #### ##    ##   ##
##  ###   ###   ## ##    ##  ###   ##   ##
##  #### ####  ##   ##   ##  ####  ##   ##
##  ## ### ## ##     ##  ##  ## ## ##   ##
##  ##     ## #########  ##  ##  ####   ##
##  ##     ## ##     ##  ##  ##   ###   ##
##  ##     ## ##     ## #### ##    ##   ##
##                                      ##
##########################################


if __name__ == '__main__':
    db.init()
    app.run(host='0.0.0.0', port=PORT, debug=True)