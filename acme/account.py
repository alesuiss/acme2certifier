#!/usr/bin/python
# -*- coding: utf-8 -*-
""" Account class """
from __future__ import print_function
import json
from acme.helper import generate_random_string, validate_email
from acme.db_handler import DBstore
from acme.message import Message

class Account(object):
    """ ACME server class """

    def __init__(self, debug=None, srv_name=None, logger=None):
        self.server_name = srv_name
        self.logger = logger
        self.dbstore = DBstore(debug, self.logger)
        self.message = Message(debug, self.server_name, self.logger)
        self.path_dic = {'acct_path' : '/acme/acct/'}

    def __enter__(self):
        """ Makes ACMEHandler a Context Manager """
        return self

    def __exit__(self, *args):
        """ cose the connection at the end of the context """

    def add(self, content, contact):
        """ prepare db insert and call DBstore helper """
        self.logger.debug('Account.account_add()')
        account_name = generate_random_string(self.logger, 12)
        # check request
        if 'alg' in content and 'jwk' in content and contact:
            # check jwk
            data_dic = {
                'name': account_name,
                'alg': content['alg'],
                'jwk': json.dumps(content['jwk']),
                'contact': json.dumps(contact),
            }

            (db_name, new) = self.dbstore.account_add(data_dic)
            self.logger.debug('god account_name:{0} new:{1}'.format(db_name, new))
            if new:
                code = 201
                message = account_name
            else:
                code = 200
                message = db_name
            detail = None
        else:
            code = 400
            message = 'urn:ietf:params:acme:error:malformed'
            detail = 'incomplete protectedpayload'

        self.logger.debug('Account.account_add() ended with:{0}'.format(code))
        return(code, message, detail)

    def contact_check(self, content):
        """ check contact information from payload"""
        self.logger.debug('Account.contact_check()')
        code = 200
        message = None
        detail = None
        if 'contact' in content:
            contact_check = validate_email(self.logger, content['contact'])
            if not contact_check:
                # invalidcontact message
                code = 400
                message = 'urn:ietf:params:acme:error:invalidContact'
                detail = ', '.join(content['contact'])
        else:
            code = 400
            message = 'urn:ietf:params:acme:error:invalidContact'
            detail = 'no contacts specified'

        self.logger.debug('Account.contact_check() ended with:{0}'.format(code))
        return(code, message, detail)

    def delete(self, aname):
        """ delete account """
        self.logger.debug('Account.delete({0})'.format(aname))
        result = self.dbstore.account_delete(aname)

        if result:
            code = 200
            message = None
            detail = None
        else:
            code = 400
            message = 'urn:ietf:params:acme:error:accountDoesNotExist'
            detail = 'deletion failed'

        self.logger.debug('Account.delete() ended with:{0}'.format(code))
        return(code, message, detail)

    def name_get(self, content):
        """ get id for account depricated"""
        self.logger.debug('Account.name_get()')
        deprecated = True
        return self.message.name_get(content)

    def new(self, content):
        """ generate a new account """
        self.logger.debug('Account.account_new()')

        response_dic = {}
        # check message but skip signature check as this is a new account (True)
        (code, message, detail, protected, payload, _account_name) = self.message.check(content, True)

        if code == 200:
            # onlyReturnExisting check
            if 'onlyreturnexisting' in payload:
                (code, message, detail) = self.onlyreturnexisting(protected, payload)
            else:
                # tos check
                (code, message, detail) = self.tos_check(payload)

                # contact check
                if code == 200:
                    (code, message, detail) = self.contact_check(payload)

                # add account to database
                if code == 200:
                    (code, message, detail) = self.add(protected, payload['contact'])

        if code == 200 or code == 201:
            response_dic['data'] = {}
            if code == 201:
                response_dic['data'] = {
                    'status': 'valid',
                    'contact': payload['contact'],
                    'orders': '{0}{1}{2}/orders'.format(self.server_name, self.path_dic['acct_path'], message),
                }
            response_dic['header'] = {}
            response_dic['header']['Location'] = '{0}{1}{2}'.format(self.server_name, self.path_dic['acct_path'], message)
        else:
            if detail == 'tosfalse':
                detail = 'Terms of service must be accepted'

        # prepare/enrich response
        status_dic = {'code': code, 'message' : message, 'detail' : detail}
        response_dic = self.message.prepare_response(response_dic, status_dic)

        self.logger.debug('Account.account_new() returns: {0}'.format(json.dumps(response_dic)))
        return response_dic

    def onlyreturnexisting(self, protected, payload):
        """ check onlyreturnexisting """
        if payload['onlyreturnexisting']:
            code = None
            message = None
            detail = None
            if 'jwk' in protected:
                if 'n' in protected['jwk']:
                    result = self.dbstore.account_lookup('modulus', protected['jwk']['n'])
                    if result:
                        code = 200
                        message = result['name']
                        detail = None
                    else:
                        code = 400
                        message = 'urn:ietf:params:acme:error:accountDoesNotExist'
                        detail = None
                else:
                    code = 400
                    message = 'urn:ietf:params:acme:error:malformed'
                    detail = 'n value missing'
            else:
                code = 400
                message = 'urn:ietf:params:acme:error:malformed'
                detail = 'jwk structure missing'

        else:
            code = 400
            message = 'urn:ietf:params:acme:error:userActionRequired'
            detail = 'onlyReturnExisting must be true'

        self.logger.debug('Account.onlyreturnexisting() ended with:{0}'.format(code))
        return(code, message, detail)

    def parse(self, content):
        """ parse message """
        self.logger.debug('Account.parse()')

        response_dic = {}
        # check message
        (code, message, detail, _protected, payload, account_name) = self.message.check(content)
        if code == 200:
            if 'status' in payload:
                if payload['status'].lower() == 'deactivated':
                    # account_name = self.message.name_get(protected)
                    (code, message, detail) = self.delete(account_name)
                    if code == 200:
                        response_dic['data'] = payload
                else:
                    code = 400
                    message = 'urn:ietf:params:acme:error:malformed'
                    detail = 'status attribute without sense'
            else:
                code = 400
                message = 'urn:ietf:params:acme:error:malformed'
                detail = 'dont know what to do with this request'
        # prepare/enrich response
        status_dic = {'code': code, 'message' : message, 'detail' : detail}
        response_dic = self.message.prepare_response(response_dic, status_dic)

        self.logger.debug('Account.account_parse() returns: {0}'.format(json.dumps(response_dic)))
        return response_dic

    def tos_check(self, content):
        """ check terms of service """
        self.logger.debug('Account.tos_check()')
        if 'termsofserviceagreed' in content:
            self.logger.debug('tos:{0}'.format(content['termsofserviceagreed']))
            if content['termsofserviceagreed']:
                code = 200
                message = None
                detail = None
            else:
                code = 403
                message = 'urn:ietf:params:acme:error:userActionRequired'
                detail = 'tosfalse'
        else:
            self.logger.debug('no tos statement found.')
            code = 403
            message = 'urn:ietf:params:acme:error:userActionRequired'
            detail = 'tosfalse'

        self.logger.debug('Account.tos_check() ended with:{0}'.format(code))
        return(code, message, detail)
