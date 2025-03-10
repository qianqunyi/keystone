# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from keystone.common import manager
import keystone.conf

CONF = keystone.conf.CONF


class Manager(manager.Manager):
    driver_namespace = 'keystone.credential.provider'
    _provides_api = 'credential_provider_api'

    def __init__(self):
        super().__init__(CONF.credential.provider)
