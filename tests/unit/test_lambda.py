import unittest
import json
import flask
from localstack.services.awslambda import lambda_api
from localstack.utils.aws.aws_models import LambdaFunction


class TestLambdaAPI(unittest.TestCase):
    CODE_SIZE = 50
    HANDLER = 'index.handler'
    RUNTIME = 'node.js4.3'
    TIMEOUT = 60  # Default value, hardcoded
    FUNCTION_NAME = 'test1'
    ALIAS_NAME = 'alias1'
    ALIAS2_NAME = 'alias2'
    RESOURCENOTFOUND_EXCEPTION = 'ResourceNotFoundException'
    RESOURCENOTFOUND_MESSAGE = 'Function not found: %s'
    ALIASEXISTS_EXCEPTION = 'ResourceConflictException'
    ALIASEXISTS_MESSAGE = 'Alias already exists: %s'
    ALIASNOTFOUND_EXCEPTION = 'ResourceNotFoundException'
    ALIASNOTFOUND_MESSAGE = 'Alias not found: %s'
    TEST_UUID = 'Test'

    def setUp(self):
        lambda_api.cleanup()
        self.maxDiff = None
        self.app = flask.Flask(__name__)

    def test_delete_event_source_mapping(self):
        with self.app.test_request_context():
            lambda_api.event_source_mappings.append({'UUID': self.TEST_UUID})
            result = lambda_api.delete_event_source_mapping(self.TEST_UUID)
            self.assertEqual(json.loads(result.get_data()).get('UUID'), self.TEST_UUID)
            self.assertEqual(0, len(lambda_api.event_source_mappings))

    def test_publish_function_version(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)

            result = json.loads(lambda_api.publish_version(self.FUNCTION_NAME).get_data())
            result2 = json.loads(lambda_api.publish_version(self.FUNCTION_NAME).get_data())

            expected_result = dict()
            expected_result['CodeSize'] = self.CODE_SIZE
            expected_result['FunctionArn'] = str(lambda_api.func_arn(self.FUNCTION_NAME)) + ':1'
            expected_result['FunctionName'] = str(self.FUNCTION_NAME)
            expected_result['Handler'] = str(self.HANDLER)
            expected_result['Runtime'] = str(self.RUNTIME)
            expected_result['Timeout'] = self.TIMEOUT
            expected_result['Version'] = '1'
            expected_result2 = dict(expected_result)
            expected_result2['FunctionArn'] = str(lambda_api.func_arn(self.FUNCTION_NAME)) + ':2'
            expected_result2['Version'] = '2'
            self.assertDictEqual(expected_result, result)
            self.assertDictEqual(expected_result2, result2)

    def test_publish_non_existant_function_version_returns_error(self):
        with self.app.test_request_context():
            result = json.loads(lambda_api.publish_version(self.FUNCTION_NAME).get_data())
            self.assertEqual(self.RESOURCENOTFOUND_EXCEPTION, result['__type'])
            self.assertEqual(self.RESOURCENOTFOUND_MESSAGE % lambda_api.func_arn(self.FUNCTION_NAME),
                             result['message'])

    def test_list_function_versions(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)
            lambda_api.publish_version(self.FUNCTION_NAME)
            lambda_api.publish_version(self.FUNCTION_NAME)

            result = json.loads(lambda_api.list_versions(self.FUNCTION_NAME).get_data())

            latest_version = dict()
            latest_version['CodeSize'] = self.CODE_SIZE
            latest_version['FunctionArn'] = str(lambda_api.func_arn(self.FUNCTION_NAME)) + ':$LATEST'
            latest_version['FunctionName'] = str(self.FUNCTION_NAME)
            latest_version['Handler'] = str(self.HANDLER)
            latest_version['Runtime'] = str(self.RUNTIME)
            latest_version['Timeout'] = self.TIMEOUT
            latest_version['Version'] = '$LATEST'
            version1 = dict(latest_version)
            version1['FunctionArn'] = str(lambda_api.func_arn(self.FUNCTION_NAME)) + ':1'
            version1['Version'] = '1'
            version2 = dict(latest_version)
            version2['FunctionArn'] = str(lambda_api.func_arn(self.FUNCTION_NAME)) + ':2'
            version2['Version'] = '2'
            expected_result = {'Versions': sorted([latest_version, version1, version2],
                                                  key=lambda k: str(k.get('Version')))}
            self.assertDictEqual(expected_result, result)

    def test_list_non_existant_function_versions_returns_error(self):
        with self.app.test_request_context():
            result = json.loads(lambda_api.list_versions(self.FUNCTION_NAME).get_data())
            self.assertEqual(self.RESOURCENOTFOUND_EXCEPTION, result['__type'])
            self.assertEqual(self.RESOURCENOTFOUND_MESSAGE % lambda_api.func_arn(self.FUNCTION_NAME),
                             result['message'])

    def test_create_alias(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)
            lambda_api.publish_version(self.FUNCTION_NAME)

            flask.request.data = json.dumps({
                'Name': self.ALIAS_NAME,
                'FunctionVersion': '1',
                'Description': ''
            })
            result = json.loads(lambda_api.create_alias(self.FUNCTION_NAME).get_data())

            expected_result = {u'AliasArn': lambda_api.func_arn(self.FUNCTION_NAME) + ":" + self.ALIAS_NAME,
                               u'FunctionVersion': '1', u'Description': '', u'Name': self.ALIAS_NAME}
            self.assertDictEqual(expected_result, result)

    def test_create_alias_on_non_existant_function_returns_error(self):
        with self.app.test_request_context():
            result = json.loads(lambda_api.create_alias(self.FUNCTION_NAME).get_data())
            self.assertEqual(self.RESOURCENOTFOUND_EXCEPTION, result['__type'])
            self.assertEqual(self.RESOURCENOTFOUND_MESSAGE % lambda_api.func_arn(self.FUNCTION_NAME),
                             result['message'])

    def test_create_alias_returns_error_if_already_exists(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)
            lambda_api.publish_version(self.FUNCTION_NAME)
            flask.request.data = json.dumps({
                'Name': self.ALIAS_NAME,
                'FunctionVersion': '1',
                'Description': ''
            })

            lambda_api.create_alias(self.FUNCTION_NAME).get_data()
            result = json.loads(lambda_api.create_alias(self.FUNCTION_NAME).get_data())
            alias_arn = lambda_api.func_arn(self.FUNCTION_NAME) + ':' + self.ALIAS_NAME
            self.assertEqual(self.ALIASEXISTS_EXCEPTION, result['__type'])
            self.assertEqual(self.ALIASEXISTS_MESSAGE % alias_arn,
                             result['message'])

    def test_update_alias(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)
            lambda_api.publish_version(self.FUNCTION_NAME)
            flask.request.data = json.dumps({
                'Name': self.ALIAS_NAME,
                'FunctionVersion': '1',
                'Description': ''
            })
            lambda_api.create_alias(self.FUNCTION_NAME).get_data()

            flask.request.data = json.dumps({
                "FunctionVersion": '$LATEST',
                "Description": 'Test-Description'
            })
            result = json.loads(lambda_api.update_alias(self.FUNCTION_NAME, self.ALIAS_NAME).get_data())

            expected_result = {'AliasArn': lambda_api.func_arn(self.FUNCTION_NAME) + ':' + self.ALIAS_NAME,
                               'FunctionVersion': '$LATEST', u'Description': 'Test-Description',
                               'Name': self.ALIAS_NAME}
            self.assertDictEqual(expected_result, result)

    def test_update_alias_on_non_existant_function_returns_error(self):
        with self.app.test_request_context():
            result = json.loads(lambda_api.update_alias(self.FUNCTION_NAME, self.ALIAS_NAME).get_data())
            self.assertEqual(self.RESOURCENOTFOUND_EXCEPTION, result['__type'])
            self.assertEqual(self.RESOURCENOTFOUND_MESSAGE % lambda_api.func_arn(self.FUNCTION_NAME),
                             result['message'])

    def test_update_alias_on_non_existant_alias_returns_error(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)
            result = json.loads(lambda_api.update_alias(self.FUNCTION_NAME, self.ALIAS_NAME).get_data())
            alias_arn = lambda_api.func_arn(self.FUNCTION_NAME) + ":" + self.ALIAS_NAME
            self.assertEqual(self.ALIASNOTFOUND_EXCEPTION, result['__type'])
            self.assertEqual(self.ALIASNOTFOUND_MESSAGE % alias_arn, result['message'])

    def test_list_aliases(self):
        with self.app.test_request_context():
            self._create_function(self.FUNCTION_NAME)
            lambda_api.publish_version(self.FUNCTION_NAME)
            flask.request.data = json.dumps({
                "Name": self.ALIAS2_NAME,
                "FunctionVersion": '$LATEST'
            })
            lambda_api.create_alias(self.FUNCTION_NAME).get_data()
            flask.request.data = json.dumps({
                'Name': self.ALIAS_NAME,
                'FunctionVersion': '1',
                'Description': self.ALIAS_NAME
            })
            lambda_api.create_alias(self.FUNCTION_NAME).get_data()

            result = json.loads(lambda_api.list_aliases(self.FUNCTION_NAME).get_data())

            expected_result = {u'Aliases': [
                {
                    'AliasArn': lambda_api.func_arn(self.FUNCTION_NAME) + ':' + self.ALIAS_NAME,
                    'FunctionVersion': '1',
                    'Name': self.ALIAS_NAME,
                    'Description': self.ALIAS_NAME
                },
                {
                    'AliasArn': lambda_api.func_arn(self.FUNCTION_NAME) + ':' + self.ALIAS2_NAME,
                    'FunctionVersion': '$LATEST',
                    'Name': self.ALIAS2_NAME,
                    'Description': ''
                }
            ]}
            self.assertDictEqual(expected_result, result)

    def test_list_non_existant_function_aliases_returns_error(self):
        with self.app.test_request_context():
            result = json.loads(lambda_api.list_aliases(self.FUNCTION_NAME).get_data())
            self.assertEqual(self.RESOURCENOTFOUND_EXCEPTION, result['__type'])
            self.assertEqual(self.RESOURCENOTFOUND_MESSAGE % lambda_api.func_arn(self.FUNCTION_NAME),
                             result['message'])

    def _create_function(self, function_name):
        arn = lambda_api.func_arn(function_name)
        lambda_api.arn_to_lambda[arn] = LambdaFunction(arn)
        lambda_api.arn_to_lambda[arn].versions = {'$LATEST': {'CodeSize': self.CODE_SIZE}}
        lambda_api.arn_to_lambda[arn].handler = self.HANDLER
        lambda_api.arn_to_lambda[arn].runtime = self.RUNTIME
        lambda_api.arn_to_lambda[arn].envvars = {}
