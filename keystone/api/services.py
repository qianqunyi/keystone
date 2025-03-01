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

# This file handles all flask-restful resources for /v3/services

import http.client

from keystone.api import validation
from keystone.catalog import schema
from keystone.common import json_home
from keystone.common import provider_api
from keystone.common import rbac_enforcer
from keystone.server import flask as ks_flask

ENFORCER = rbac_enforcer.RBACEnforcer
PROVIDERS = provider_api.ProviderAPIs


class ServicesResource(ks_flask.ResourceBase):
    collection_key = 'services'
    member_key = 'service'

    @validation.request_query_schema(schema.service_index_request_query)
    @validation.response_body_schema(schema.service_index_response_body)
    def get(self):
        """List all services.

        GET /v3/services
        """
        filters = ['type', 'name']
        ENFORCER.enforce_call(action='identity:list_services', filters=filters)
        hints = self.build_driver_hints(filters)
        refs = PROVIDERS.catalog_api.list_services(hints=hints)
        return self.wrap_collection(refs, hints=hints)

    @validation.request_body_schema(schema.service_create_request_body)
    @validation.response_body_schema(schema.service_response_body)
    def post(self):
        """Create new services.

        POST /v3/services
        """
        ENFORCER.enforce_call(action='identity:create_service')
        service = self.request_body_json.get('service')
        service = self._assign_unique_id(self._normalize_dict(service))
        ref = PROVIDERS.catalog_api.create_service(
            service['id'], service, initiator=self.audit_initiator
        )
        return self.wrap_member(ref), http.client.CREATED


class ServiceResource(ks_flask.ResourceBase):
    collection_key = 'services'
    member_key = 'service'

    @validation.request_query_schema(schema.service_index_request_query)
    @validation.response_body_schema(schema.service_response_body)
    def get(self, service_id):
        """Show details for a service.

        GET /v3/services/{service_id}
        """
        ENFORCER.enforce_call(action='identity:get_service')
        return self.wrap_member(PROVIDERS.catalog_api.get_service(service_id))

    @validation.request_body_schema(schema.service_update_request_body)
    @validation.response_body_schema(schema.service_response_body)
    def patch(self, service_id):
        """Update existing services.

        PATCH /v3/services/{service_id}
        """
        ENFORCER.enforce_call(action='identity:update_service')
        service = self.request_body_json.get('service')
        self._require_matching_id(service)
        ref = PROVIDERS.catalog_api.update_service(
            service_id, service, initiator=self.audit_initiator
        )
        return self.wrap_member(ref)

    def delete(self, service_id):
        ENFORCER.enforce_call(action='identity:delete_service')
        return (
            PROVIDERS.catalog_api.delete_service(
                service_id, initiator=self.audit_initiator
            ),
            http.client.NO_CONTENT,
        )


class ServiceAPI(ks_flask.APIBase):
    _name = 'services'
    _import_name = __name__
    resource_mapping = [
        ks_flask.construct_resource_map(
            resource=ServicesResource,
            url='/services',
            resource_kwargs={},
            rel="services",
            path_vars=None,
        ),
        ks_flask.construct_resource_map(
            resource=ServiceResource,
            url='/services/<string:service_id>',
            resource_kwargs={},
            rel="service",
            path_vars={'service_id': json_home.Parameters.SERVICE_ID},
        ),
    ]


APIs = (ServiceAPI,)
