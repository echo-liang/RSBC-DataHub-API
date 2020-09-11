import python.common.helper as helper
from python.ingestor.config import Config
from python.common.rabbitmq import RabbitMQ
from python.common.message import encode_message
import python.common.business as rules
import python.common.vips_api as vips
from flask import request, jsonify, Response, make_response
from flask_api import FlaskAPI
from datetime import datetime
import base64
import xmltodict
import logging
import json
import re
from functools import wraps


application = FlaskAPI(__name__)
application.secret = Config.FLASK_SECRET_KEY
logging.basicConfig(level=Config.LOG_LEVEL)
logging.warning('*** flask initialized ***')

rabbit_mq = RabbitMQ(
        Config.RABBITMQ_USER,
        Config.RABBITMQ_PASS,
        Config.RABBITMQ_URL,
        Config.LOG_LEVEL,
        Config.MAX_CONNECTION_RETRIES,
        Config.RETRY_DELAY)

available_parameters = helper.load_json_into_dict('python/ingestor/' + Config.PARAMETERS_FILE)


def basic_auth_required(f):
    """
    Decorator that implements basic auth when added to a route
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_credentials(Config, auth.username, auth.password):
            message = {'error': 'Unauthorized'}
            resp = jsonify(message)
            resp.status_code = 401
            return resp
        return f(*args, **kwargs)
    return decorated


@application.route('/v1/publish/event/ETK', methods=["POST"])
@application.route('/v1/publish/event', methods=["POST"])
def ingest_etk():
    if request.method == 'POST':
        payload = request.json
        encoded_message = encode_message(payload, Config.ENCRYPT_KEY)
        if payload is not None and rabbit_mq.publish(available_parameters['form']['queue'], encoded_message):
            return jsonify(payload), 200
        else:
            return Response('Unavailable', 500, mimetype='application/json')


@application.route('/v1/publish/event/form', methods=["POST"])
def ingest_form():
    if request.method == 'POST' and request.content_type == 'application/xml':
        form_name = request.args.get('form')
        payload = {
            "event_version": "1.4",
            "encrypt_at_rest": available_parameters['form']['encrypt_at_rest'],
            "event_date_time": datetime.now().isoformat(),
            "url_parameters": request.args.to_dict(),
            "event_type": form_name,
            form_name: xmltodict.parse(request.get_data())
        }
        payload[form_name]['xml'] = base64.b64encode(request.get_data()).decode()
        encoded_message = encode_message(payload, Config.ENCRYPT_KEY)
        if payload is not None and rabbit_mq.publish(available_parameters['form']['queue'], encoded_message):
            return jsonify(payload), 200
        else:
            return Response('Unavailable', 500, mimetype='application/json')


@application.route('/schedule', methods=['POST'])
@basic_auth_required
def schedule():
    """
    Confirm prohibition number and last name matches VIPS.
    Return list of possible review dates for given prohibition.
    Note: using POST instead of GET to allow last names with
    special characters from Orbeon.
    """
    if request.method == 'POST':
        # invoke middleware functions
        args = helper.middle_logic(rules.ready_for_scheduling(),
                                   prohibition_number=request.form['prohibition_number'],
                                   driver_last_name=request.form['last_name'],
                                   config=Config)
        if 'error_string' not in args:
            return jsonify(dict({
                "data": {
                    "is_valid": True,
                    "presentation_type": args.get('presentation_type'),
                    "time_slots": args.get('time_slots')
                }
            }))
        return jsonify(dict({
                    "data": {
                        "is_success": False,
                        "error": args.get('error_string'),
                        "timeSlots": []
                    }
                }))


def check_credentials(config, username_submitted, password_submitted) -> bool:
    username = config.FLASK_BASIC_AUTH_USER
    password = config.FLASK_BASIC_AUTH_PASS
    logging.info('credentials: {}:{}'.format(username, password))
    if username_submitted == username and password_submitted == password:
        return True
    return False


if __name__ == "__main__":
    application.run(host='0.0.0.0')