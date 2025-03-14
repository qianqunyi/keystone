#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# This file handles all flask-restful resources for /v3/credentials

import hashlib
import http.client

import flask
from oslo_serialization import jsonutils

from keystone.api import validation
from keystone.common import json_home
from keystone.common import provider_api
from keystone.common import rbac_enforcer
import keystone.conf
from keystone.credential import schema
from keystone import exception
from keystone.i18n import _
from keystone.server import flask as ks_flask

CONF = keystone.conf.CONF
PROVIDERS = provider_api.ProviderAPIs
ENFORCER = rbac_enforcer.RBACEnforcer


def _build_target_enforcement():
    target = {}
    try:
        target['credential'] = PROVIDERS.credential_api.get_credential(
            flask.request.view_args.get('credential_id')
        )
    except exception.NotFound:  # nosec
        # Defer existance in the event the credential doesn't exist, we'll
        # check this later anyway.
        pass

    return target


def _blob_to_json(ref: dict) -> dict:
    """Serialize blob as string."""
    # credentials stored via ec2tokens before the fix for #1259584
    # need json_serailzing, as that's the documented API format
    blob = ref.get('blob')
    if isinstance(blob, dict):
        ref = ref.copy()
        ref['blob'] = jsonutils.dumps(blob)
    return ref


def _validate_blob_json(ref: dict) -> dict:
    """Validate `blob` is a valid object."""
    try:
        blob = jsonutils.loads(ref.get('blob'))
    except (ValueError, TabError):
        raise exception.ValidationError(
            message=_('Invalid blob in credential')
        )
    if not blob or not isinstance(blob, dict):
        raise exception.ValidationError(attribute='blob', target='credential')
    if blob.get('access') is None:
        raise exception.ValidationError(
            attribute='access', target='credential'
        )
    return blob


class CredentialsResource(ks_flask.ResourceBase):
    collection_key = 'credentials'
    member_key = 'credential'

    @staticmethod
    def _blob_to_json(ref):
        # credentials stored via ec2tokens before the fix for #1259584
        # need json_serailzing, as that's the documented API format
        blob = ref.get('blob')
        if isinstance(blob, dict):
            ref = ref.copy()
            ref['blob'] = jsonutils.dumps(blob)
        return ref

    def _validate_blob_json(self, ref):
        try:
            blob = jsonutils.loads(ref.get('blob'))
        except (ValueError, TabError):
            raise exception.ValidationError(
                message=_('Invalid blob in credential')
            )
        if not blob or not isinstance(blob, dict):
            raise exception.ValidationError(
                attribute='blob', target='credential'
            )
        if blob.get('access') is None:
            raise exception.ValidationError(
                attribute='access', target='credential'
            )
        return blob

    def _assign_unique_id(
        self, ref, trust_id=None, app_cred_id=None, access_token_id=None
    ):
        # Generates an assigns a unique identifier to a credential reference.
        if ref.get('type', '').lower() == 'ec2':
            blob = _validate_blob_json(ref)
            ref = ref.copy()
            ref['id'] = hashlib.sha256(
                blob['access'].encode('utf8')
            ).hexdigest()
            # update the blob with the trust_id or app_cred_id, so credentials
            # created with a trust- or app cred-scoped token will result in
            # trust- or app cred-scoped tokens when authentication via
            # ec2tokens happens
            if trust_id is not None:
                blob['trust_id'] = trust_id
                ref['blob'] = jsonutils.dumps(blob)
            if app_cred_id is not None:
                blob['app_cred_id'] = app_cred_id
                ref['blob'] = jsonutils.dumps(blob)
            if access_token_id is not None:
                blob['access_token_id'] = access_token_id
                ref['blob'] = jsonutils.dumps(blob)
            return ref
        else:
            return super()._assign_unique_id(ref)

    @validation.request_query_schema(schema.index_request_query)
    @validation.response_body_schema(schema.index_response_body)
    def get(self):
        """List credentials.

        GET /v3/credentials
        """
        filters = ['user_id', 'type']
        if not self.oslo_context.system_scope:
            target = {'credential': {'user_id': self.oslo_context.user_id}}
        else:
            target = None
        ENFORCER.enforce_call(
            action='identity:list_credentials',
            filters=filters,
            target_attr=target,
        )
        hints = self.build_driver_hints(filters)
        refs = PROVIDERS.credential_api.list_credentials(hints)
        # If the request was filtered, make sure to return only the
        # credentials specific to that user. This makes it so that users with
        # roles on projects can't see credentials that aren't theirs.
        filtered_refs = []
        for ref in refs:
            # Check each credential again to make sure the user has access to
            # it, either by owning it, being a project admin with
            # enforce_scope=false, being a system user, or having some other
            # custom policy that allows access.
            try:
                cred = PROVIDERS.credential_api.get_credential(ref['id'])
                ENFORCER.enforce_call(
                    action='identity:get_credential',
                    target_attr={'credential': cred},
                )
                filtered_refs.append(ref)
            except exception.Forbidden:
                pass
        refs = filtered_refs
        refs = [_blob_to_json(r) for r in refs]
        return self.wrap_collection(refs, hints=hints)

    @validation.request_body_schema(schema.create_request_body)
    @validation.response_body_schema(schema.credential_response_body)
    def post(self):
        """Create new credentials.

        POST /v3/credentials
        """
        credential = self.request_body_json.get('credential', {})
        target = {}
        target['credential'] = credential
        ENFORCER.enforce_call(
            action='identity:create_credential', target_attr=target
        )
        trust_id = getattr(self.oslo_context, 'trust_id', None)
        app_cred_id = getattr(
            self.auth_context['token'], 'application_credential_id', None
        )
        access_token_id = getattr(
            self.auth_context['token'], 'access_token_id', None
        )
        ref = self._assign_unique_id(
            self._normalize_dict(credential),
            trust_id=trust_id,
            app_cred_id=app_cred_id,
            access_token_id=access_token_id,
        )
        ref = PROVIDERS.credential_api.create_credential(
            ref['id'], ref, initiator=self.audit_initiator
        )
        return self.wrap_member(ref), http.client.CREATED


class CredentialResource(ks_flask.ResourceBase):
    collection_key = 'credentials'
    member_key = 'credential'

    def _validate_blob_update_keys(self, credential, ref):
        if credential.get('type', '').lower() == 'ec2':
            new_blob = _validate_blob_json(ref)
            old_blob = credential.get('blob')
            if isinstance(old_blob, str):
                old_blob = jsonutils.loads(old_blob)
            # if there was a scope set, prevent changing it or unsetting it
            for key in [
                'trust_id',
                'app_cred_id',
                'access_token_id',
                'access_id',
            ]:
                if old_blob.get(key) != new_blob.get(key):
                    message = _('%s can not be updated for credential') % key
                    raise exception.ValidationError(message=message)

    @validation.response_body_schema(schema.credential_response_body)
    def get(self, credential_id: str):
        """Retrieve existing credentials.

        GET /v3/credentials/{credential_id}
        """
        # Get Credential.
        ENFORCER.enforce_call(
            action='identity:get_credential',
            build_target=_build_target_enforcement,
        )
        credential = PROVIDERS.credential_api.get_credential(credential_id)
        return self.wrap_member(_blob_to_json(credential))

    @validation.request_body_schema(schema.update_request_body)
    @validation.response_body_schema(schema.credential_response_body)
    def patch(self, credential_id: str):
        """Update existing credentials.

        PATCH /v3/credentials/{credential_id}
        """
        ENFORCER.enforce_call(
            action='identity:update_credential',
            build_target=_build_target_enforcement,
        )
        current = PROVIDERS.credential_api.get_credential(credential_id)

        credential = self.request_body_json.get('credential', {})
        self._validate_blob_update_keys(current.copy(), credential.copy())
        self._require_matching_id(credential)
        # Check that the user hasn't illegally modified the owner or scope
        target = {'credential': dict(current, **credential)}
        ENFORCER.enforce_call(
            action='identity:update_credential', target_attr=target
        )
        ref = PROVIDERS.credential_api.update_credential(
            credential_id, credential
        )
        return self.wrap_member(ref)

    def delete(self, credential_id: str):
        """Delete credentials.

        DELETE /v3/credentials/{credential_id}
        """
        ENFORCER.enforce_call(
            action='identity:delete_credential',
            build_target=_build_target_enforcement,
        )

        return (
            PROVIDERS.credential_api.delete_credential(
                credential_id, initiator=self.audit_initiator
            ),
            http.client.NO_CONTENT,
        )


class CredentialAPI(ks_flask.APIBase):
    _name = 'credentials'
    _import_name = __name__
    resource_mapping = [
        ks_flask.construct_resource_map(
            resource=CredentialsResource,
            url='/credentials',
            resource_kwargs={},
            rel="credentials",
            path_vars=None,
        ),
        ks_flask.construct_resource_map(
            resource=CredentialResource,
            url='/credentials/<string:credential_id>',
            resource_kwargs={},
            rel="credential",
            path_vars={
                'credential_id': json_home.build_v3_parameter_relation(
                    "credential_id"
                )
            },
        ),
    ]


APIs = (CredentialAPI,)
