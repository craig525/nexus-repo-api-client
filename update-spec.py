#
# Copyright 2019-Present Sonatype Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json
import os.path
import sys
from functools import wraps

import requests
from yaml import dump as yaml_dump

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    pass

NXRM_SPEC_PATH = "/service/rest/swagger.json"


def parse_version_from_server_header(header: str) -> str:
    return header.split("/")[1].split(" ")[0]


def progress_block(title: str, detail: bool = False):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            print(title)
            result = function(*args, **kwargs)
            if detail and result is not None:
                print(f"     {result}")
            print("     Done")
            return result

        return wrapped

    return decorate


def load_spec(server_url: str) -> tuple[dict, str]:
    response = requests.get(f"{server_url}{NXRM_SPEC_PATH}")
    version = parse_version_from_server_header(response.headers.get("Server", ""))
    swagger_spec = response.json()
    converted_response = requests.post(
        "https://converter.swagger.io/api/convert", json=swagger_spec
    )
    return converted_response.json(), version


def write_spec(spec: dict) -> None:
    with open("./spec/openapi.yaml", "w") as output_yaml_specfile:
        output_yaml_specfile.write(yaml_dump(spec))


@progress_block("Updating `info`")
def patch_info(json_spec: dict, nxrm_version: str) -> None:
    json_spec["info"] = {
        "title": "Sonatype Nexus Repository Manager",
        "description": "This documents the available APIs into [Sonatype Nexus Repository Manager]"
        "(https://www.sonatype.com/products/sonatype-nexus-repository) as of version "
        + nxrm_version
        + ".",
        "contact": {
            "name": "Sonatype Community Maintainers",
            "url": "https://github.com/sonatype-nexus-community",
        },
        "license": {
            "name": "Apache-2.0",
            "url": "http://www.apache.org/licenses/LICENSE-2.0.html",
        },
        "version": nxrm_version,
    }


@progress_block("Updating security schemes")
def patch_security(json_spec: dict, _nxrm_version: str) -> None:
    if "components" in json_spec and "securitySchemes" not in json_spec["components"]:
        json_spec["components"]["securitySchemes"] = {
            "BasicAuth": {"type": "http", "scheme": "basic"}
        }
    if "security" not in json_spec:
        json_spec["security"] = [{"BasicAuth": []}]


@progress_block("Fixing repository OperationIDs", detail=True)
def patch_repository_operation_ids(json_spec: dict, _nxrm_version: str) -> str:
    json_spec["paths"]["/v1/repositories"]["get"]["operationId"] = "getAllRepositories"
    count = 0
    for path in json_spec["paths"]:
        if str(path).startswith("/v1/repositories/"):
            path_parts = str(path).split("/")
            if len(path_parts) > 4:
                format = path_parts[3]
                type = path_parts[4]
                for method in json_spec["paths"][path]:
                    if str(method).lower() == "get":
                        json_spec["paths"][path]["get"]["operationId"] = (
                            f"get{format.capitalize()}{type.capitalize()}Repository"
                        )
                        count += 1
                    if str(method).lower() == "post":
                        json_spec["paths"][path]["post"]["operationId"] = (
                            f"create{format.capitalize()}{type.capitalize()}Repository"
                        )
                        count += 1
                    if str(method).lower() == "put":
                        json_spec["paths"][path]["put"]["operationId"] = (
                            f"update{format.capitalize()}{type.capitalize()}Repository"
                        )
                        count += 1
    return f"Fixed {count} Repository Operations"


@progress_block("Fixing privilege OperationIDs", detail=True)
def patch_privilege_operation_ids(json_spec: dict, _nxrm_version: str) -> str:
    count = 0
    for path in json_spec["paths"]:
        if str(path).startswith("/v1/security/privileges/"):
            path_parts = str(path).split("/")
            if len(path_parts) > 4:
                privilege_type = path_parts[4]
                for method in json_spec["paths"][path]:
                    if str(method).lower() == "post":
                        json_spec["paths"][path]["post"]["operationId"] = (
                            f"create{privilege_type.capitalize()}Privilege"
                        )
                        count += 1
                    if str(method).lower() == "put":
                        json_spec["paths"][path]["put"]["operationId"] = (
                            f"update{privilege_type.capitalize()}Privilege"
                        )
                        count += 1
    return f"Fixed {count} Privilege Operations"


@progress_block("Correcting privilege response schemas")
def patch_privilege_response_schemas(json_spec: dict, _nxrm_version: str) -> None:
    with open(
        os.path.join(os.path.dirname(__file__), "snippets", "ApiPrivilegeRequest.json"),
        "r",
    ) as snippet:
        json_spec["components"]["schemas"]["ApiPrivilegeRequest"] = json.load(snippet)

    json_spec["paths"]["/v1/security/privileges"]["get"]["operationId"] = (
        "getAllPrivileges"
    )
    if "200" not in json_spec["paths"]["/v1/security/privileges"]["get"]["responses"]:
        json_spec["paths"]["/v1/security/privileges"]["get"]["responses"]["200"] = {}
    json_spec["paths"]["/v1/security/privileges"]["get"]["responses"]["200"][
        "content"
    ] = {
        "application/json": {
            "schema": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/ApiPrivilegeRequest"},
            }
        }
    }
    privilege_path = "/v1/security/privileges/{privilegeName}"
    if "200" not in json_spec["paths"][privilege_path]["get"]["responses"]:
        json_spec["paths"][privilege_path]["get"]["responses"]["200"] = {}
    json_spec["paths"][privilege_path]["get"]["responses"]["200"]["content"] = {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/ApiPrivilegeRequest"}
        }
    }


@progress_block("Patching storage and HTTP attributes")
def patch_storage_and_http_attributes(json_spec: dict, _nxrm_version: str) -> None:
    json_spec["components"]["schemas"]["StorageAttributes"]["properties"][
        "writePolicy"
    ] = {
        "description": "Controls if deployments of and updates to assets are allowed",
        "enum": ["allow", "allow_once", "deny"],
        "example": "allow_once",
        "type": "string",
    }
    json_spec["components"]["schemas"]["HttpClientConnectionAuthenticationAttributes"][
        "properties"
    ]["preemptive"] = {
        "description": "Whether to use pre-emptive authentication. Use with caution. Defaults to false.",
        "example": "false",
        "type": "boolean",
    }


@progress_block("Overriding selected operation IDs", detail=True)
def patch_selected_operation_ids(json_spec: dict, _nxrm_version: str) -> None:
    operations_to_fix = [
        {
            "path": "/v1/blobstores/s3",
            "method": "post",
            "operation_id": "CreateS3BlobStore",
        },
        {
            "path": "/v1/blobstores/s3/{name}",
            "method": "get",
            "operation_id": "GetS3BlobStore",
        },
        {
            "path": "/v1/blobstores/s3/{name}",
            "method": "put",
            "operation_id": "UpdateS3BlobStore",
        },
        {
            "path": "/v1/plan/{planId}",
            "method": "delete",
            "operation_id": "DeletePlanId",
        },
        {"path": "/v1/plan/{planId}", "method": "put", "operation_id": "UpdatePlanId"},
    ]
    for operation in operations_to_fix:
        print(
            f"    Setting OperationID to {operation['operation_id']} "
            f"for {operation['method']}:{operation['path']}"
        )
        json_spec["paths"][operation["path"]][operation["method"]]["operationId"] = (
            operation["operation_id"]
        )


@progress_block("Patching LDAP schemas and responses")
def patch_ldap_schemas(json_spec: dict, _nxrm_version: str) -> None:
    json_spec["paths"]["/v1/security/ldap"]["get"]["responses"]["200"]["content"] = {
        "application/json": {
            "schema": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/ReadLdapServerXo"},
            }
        }
    }
    json_spec["paths"]["/v1/security/ldap/{name}"]["get"]["responses"]["200"][
        "content"
    ] = {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/ReadLdapServerXo"}
        }
    }
    required = json_spec["components"]["schemas"]["CreateLdapServerXo"]["required"]
    # required.remove('groupType') Removed for 3.90.1
    json_spec["components"]["schemas"]["CreateLdapServerXo"]["required"] = required
    json_spec["components"]["schemas"]["ReadLdapServerXo"]["required"] = required
    json_spec["components"]["schemas"]["UpdateLdapServerXo"]["required"] = required


@progress_block("Adding missing success responses")
def patch_missing_success_responses(json_spec: dict, _nxrm_version: str) -> None:
    paths_missing_201: dict[str, list[str]] = {
        "/v1/security/privileges/application": ["post"],
        "/v1/security/privileges/repository-admin": ["post"],
        "/v1/security/privileges/repository-content-selector": ["post"],
        "/v1/security/privileges/repository-view": ["post"],
        "/v1/security/privileges/script": ["post"],
        "/v1/security/privileges/wildcard": ["post"],
    }
    for path, methods in paths_missing_201.items():
        for method in methods:
            json_spec["paths"][path][method]["responses"].update(
                {"201": {"content": {}, "description": "Success"}}
            )

    paths_missing_204: dict[str, list[str]] = {
        "/v1/security/privileges/application/{privilegeName}": ["put"],
        "/v1/security/privileges/repository-admin/{privilegeName}": ["put"],
        "/v1/security/privileges/repository-content-selector/{privilegeName}": ["put"],
        "/v1/security/privileges/repository-view/{privilegeName}": ["put"],
        "/v1/security/privileges/script/{privilegeName}": ["put"],
        "/v1/security/privileges/wildcard/{privilegeName}": ["put"],
        "/v1/security/roles/{id}": ["delete"],
        "/v1/security/users/{userId}": ["put"],
        "/v1/security/users/{userId}/change-password": ["put"],
    }
    for path, methods in paths_missing_204.items():
        for method in methods:
            json_spec["paths"][path][method]["responses"].update(
                {"204": {"content": {}, "description": "Success"}}
            )


@progress_block("Correcting InputStream schema")
def patch_input_stream_schema(json_spec: dict, _nxrm_version: str) -> None:
    json_spec["components"]["schemas"]["InputStream"] = {
        "type": "string",
        "format": "binary",
    }


@progress_block("Adding missing response descriptions")
def add_missing_response_descriptions(json_spec: dict, _nxrm_version: str) -> None:
    for path in json_spec["paths"]:
        for method in json_spec["paths"][path]:
            if "responses" in json_spec["paths"][path][method]:
                for response_code in json_spec["paths"][path][method]["responses"]:
                    response = json_spec["paths"][path][method]["responses"][
                        response_code
                    ]
                    if "description" not in response:
                        response["description"] = ""


@progress_block("Patching Docker, PyPI, and writable-member repositories")
def patch_docker_pypi_and_writable_member_repositories(
    json_spec: dict, _nxrm_version: str
) -> None:
    json_spec["components"]["schemas"]["DockerHostedApiRepository"]["properties"][
        "storage"
    ] = {"$ref": "#/components/schemas/DockerHostedStorageAttributes"}

    json_spec["components"]["schemas"].update(
        {
            "PyPiProxyApiRepository": {
                "properties": {
                    "cleanup": {"$ref": "#/components/schemas/CleanupPolicyAttributes"},
                    "format": {"type": "string", "default": "pypi"},
                    "httpClient": {"$ref": "#/components/schemas/HttpClientAttributes"},
                    "name": {
                        "description": "A unique identifier for this repository",
                        "pattern": "^[a-zA-Z0-9\\-]{1}[a-zA-Z0-9_\\-\\.]*$",
                        "type": "string",
                    },
                    "negativeCache": {
                        "$ref": "#/components/schemas/NegativeCacheAttributes"
                    },
                    "online": {
                        "description": "Whether this repository accepts incoming requests",
                        "type": "boolean",
                    },
                    "proxy": {"$ref": "#/components/schemas/ProxyAttributes"},
                    "pypi": {"$ref": "#/components/schemas/PyPiProxyAttributes"},
                    "replication": {
                        "$ref": "#/components/schemas/ReplicationAttributes"
                    },
                    "routingRuleName": {"type": "string"},
                    "storage": {"$ref": "#/components/schemas/StorageAttributes"},
                    "type": {"type": "string", "default": "proxy"},
                    "url": {"type": "string"},
                },
                "required": [
                    "format",
                    "httpClient",
                    "name",
                    "negativeCache",
                    "online",
                    "proxy",
                    "pypi",
                    "storage",
                    "type",
                    "url",
                ],
            }
        }
    )
    json_spec["paths"]["/v1/repositories/pypi/proxy/{repositoryName}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ] = "#/components/schemas/PyPiProxyApiRepository"

    paths_to_fix_writable_member = ["/v1/repositories/pypi/group/{repositoryName}"]
    for path in paths_to_fix_writable_member:
        json_spec["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] = {"$ref": "#/components/schemas/SimpleApiGroupDeployRepository"}


@progress_block("Patching Raw, Cargo, and Conan repositories")
def patch_raw_cargo_and_conan_repositories(json_spec: dict, _nxrm_version: str) -> None:
    json_spec["components"]["schemas"].update(
        {
            "RawGroupApiRepository": {
                "properties": {
                    "format": {"type": "string", "default": "raw"},
                    "group": {"$ref": "#/components/schemas/GroupAttributes"},
                    "name": {
                        "description": "A unique identifier for this repository",
                        "pattern": "^[a-zA-Z0-9\\-]{1}[a-zA-Z0-9_\\-\\.]*$",
                        "type": "string",
                    },
                    "online": {
                        "description": "Whether this repository accepts incoming requests",
                        "type": "boolean",
                    },
                    "raw": {"$ref": "#/components/schemas/RawAttributes"},
                    "storage": {"$ref": "#/components/schemas/StorageAttributes"},
                    "type": {"type": "string", "default": "group"},
                    "url": {"type": "string"},
                },
                "required": [
                    "format",
                    "group",
                    "name",
                    "online",
                    "raw",
                    "storage",
                    "type",
                    "url",
                ],
            }
        }
    )
    for path, schema in {
        "/v1/repositories/raw/group/{repositoryName}": "RawGroupApiRepository",
        "/v1/repositories/raw/hosted/{repositoryName}": "RawHostedApiRepository",
        "/v1/repositories/raw/proxy/{repositoryName}": "RawProxyApiRepository",
    }.items():
        if "200" not in json_spec["paths"][path]["get"]["responses"]:
            json_spec["paths"][path]["get"]["responses"] = {
                "200": {"content": {"application/json": {"schema": {}}}}
            }
        json_spec["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] = {"$ref": f"#/components/schemas/{schema}"}
    json_spec["components"]["schemas"].update(
        {
            "RawHostedApiRepository": {
                "properties": {
                    "cleanup": {"$ref": "#/components/schemas/CleanupPolicyAttributes"},
                    "component": {"$ref": "#/components/schemas/ComponentAttributes"},
                    "format": {"type": "string", "default": "raw"},
                    "name": {
                        "description": "A unique identifier for this repository",
                        "pattern": "^[a-zA-Z0-9\\-]{1}[a-zA-Z0-9_\\-\\.]*$",
                        "type": "string",
                    },
                    "online": {
                        "description": "Whether this repository accepts incoming requests",
                        "type": "boolean",
                    },
                    "raw": {"$ref": "#/components/schemas/RawAttributes"},
                    "storage": {"$ref": "#/components/schemas/HostedStorageAttributes"},
                    "type": {"type": "string", "default": "hosted"},
                    "url": {"type": "string"},
                },
                "required": [
                    "format",
                    "name",
                    "online",
                    "raw",
                    "storage",
                    "type",
                    "url",
                ],
            },
            "RawProxyApiRepository": {
                "properties": {
                    "cleanup": {"$ref": "#/components/schemas/CleanupPolicyAttributes"},
                    "format": {"type": "string", "default": "pypi"},
                    "httpClient": {"$ref": "#/components/schemas/HttpClientAttributes"},
                    "name": {
                        "description": "A unique identifier for this repository",
                        "pattern": "^[a-zA-Z0-9\\-]{1}[a-zA-Z0-9_\\-\\.]*$",
                        "type": "string",
                    },
                    "negativeCache": {
                        "$ref": "#/components/schemas/NegativeCacheAttributes"
                    },
                    "online": {
                        "description": "Whether this repository accepts incoming requests",
                        "type": "boolean",
                    },
                    "proxy": {"$ref": "#/components/schemas/ProxyAttributes"},
                    "raw": {"$ref": "#/components/schemas/RawAttributes"},
                    "replication": {
                        "$ref": "#/components/schemas/ReplicationAttributes"
                    },
                    "routingRuleName": {"type": "string"},
                    "storage": {"$ref": "#/components/schemas/StorageAttributes"},
                    "type": {"type": "string", "default": "raw"},
                    "url": {"type": "string"},
                },
                "required": [
                    "format",
                    "httpClient",
                    "name",
                    "negativeCache",
                    "online",
                    "proxy",
                    "raw",
                    "storage",
                    "type",
                    "url",
                ],
            },
        }
    )
    json_spec["components"]["schemas"]["CargoGroupApiRepository"]["properties"][
        "group"
    ] = {"$ref": "#/components/schemas/GroupAttributes"}
    json_spec["paths"]["/v1/repositories/conan/group/{repositoryName}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"] = {
        "$ref": "#/components/schemas/SimpleApiGroupDeployRepository"
    }


@progress_block("Patching task endpoints")
def patch_task_endpoints(json_spec: dict, nxrm_version: str) -> None:
    task_key = "/v1/tasks/{taskId}"
    if int(nxrm_version.split(".")[1]) >= 94:
        json_spec["paths"][task_key] = json_spec["paths"]["/v1/tasks/{id}"]
        del json_spec["paths"]["/v1/tasks/{id}"]
        for method in json_spec["paths"][task_key]:
            for parameter in json_spec["paths"][task_key][method].get("parameters", []):
                if parameter["name"] == "id":
                    parameter["name"] = "taskId"
    if "put" not in json_spec["paths"][task_key]:
        json_spec["paths"][task_key]["put"] = {
            "parameters": [
                {
                    "name": "taskId",
                    "in": "path",
                    "description": "Id of the task to get",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {"content": {"application/json": {}}},
            "responses": {"200": {}},
        }
    json_spec["paths"][task_key]["put"]["requestBody"]["content"]["application/json"][
        "schema"
    ] = {
        "properties": {
            "alertEmail": {
                "description": "e-mail for task notifications.",
                "type": "string",
            },
            "enabled": {
                "description": "Indicates if the task would be enabled.",
                "type": "boolean",
            },
            # Not present in the Nexus 3.94.x task schema.
            # "frequency": {"$ref": "#/components/schemas/FrequencyXO"},
            "name": {"description": "The name of the task template.", "type": "string"},
            "notificationCondition": {
                "description": "Condition required to notify a task execution.",
                "enum": ["FAILURE", "SUCCESS_FAILURE"],
                "type": "string",
            },
            "properties": {
                "additionalProperties": {"type": "string"},
                "description": "Additional properties for the task",
                "type": "object",
            },
            "type": {
                "description": "The type of task to be created.",
                "type": "string",
            },
        },
        # Not present in the Nexus 3.94.x task schema.
        # "required": ["enabled", "frequency", "name", "notificationCondition"],
        "required": ["enabled", "name", "notificationCondition"],
    }
    if "post" not in json_spec["paths"]["/v1/tasks"]:
        json_spec["paths"]["/v1/tasks"]["post"] = {}
    json_spec["paths"]["/v1/tasks"]["post"]["responses"] = {
        "201": {
            "content": {
                "application/json": {
                    "schema": {
                        "properties": {
                            "id": {
                                "description": "Task ID",
                                "format": "uuid",
                                "type": "string",
                            }
                        },
                        "required": ["id"],
                    }
                }
            },
            "description": "Task created successfully",
        }
    }


@progress_block(
    "Patching component, tag, proxy, nullable, IQ, Terraform, and Swift schemas"
)
def patch_component_tag_proxy_nullable_iq_terraform_swift(
    json_spec: dict, _nxrm_version: str
) -> None:
    json_spec["components"]["schemas"]["ComponentXO"]["properties"]["tags"] = {
        "items": {"type": "string"},
        "type": "array",
    }
    if "TagXO" not in json_spec["components"]["schemas"]:
        json_spec["components"]["schemas"]["TagXO"] = {"properties": {}}
    json_spec["components"]["schemas"]["TagXO"]["properties"]["attributes"] = {
        "additionalProperties": {},
        "type": "object",
    }
    json_spec["components"]["schemas"].update(
        {
            "ConanProxyApiRepository": {
                "allOf": [
                    {"$ref": "#/components/schemas/ConanProxyRepositoryApiRequest"},
                    {
                        "type": "object",
                        "required": ["format", "type", "url"],
                        "properties": {
                            "format": {"type": "string", "default": "conan"},
                            "type": {"type": "string", "default": "proxy"},
                            "url": {"type": "string"},
                            "routingRuleName": {
                                "description": "The name of the routing rule assigned to this repository",
                                "type": "string",
                            },
                        },
                    },
                ]
            }
        }
    )
    conan_path = "/v1/repositories/conan/proxy/{repositoryName}"
    if "200" not in json_spec["paths"][conan_path]["get"]["responses"]:
        json_spec["paths"][conan_path]["get"]["responses"]["200"] = {
            "content": {"application/json": {}}
        }
    json_spec["paths"][conan_path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] = {"$ref": "#/components/schemas/ConanProxyApiRepository"}
    for name in ("HttpSettingsXo", "ProxySettingsXo"):
        if name not in json_spec["components"]["schemas"]:
            json_spec["components"]["schemas"][name] = (
                {"properties": {"nonProxyHosts": {}, "userAgent": {}}}
                if name == "HttpSettingsXo"
                else {}
            )
    json_spec["components"]["schemas"]["HttpSettingsXo"]["properties"][
        "nonProxyHosts"
    ].update({"nullable": "true"})
    json_spec["components"]["schemas"]["HttpSettingsXo"]["properties"][
        "userAgent"
    ].update({"nullable": "true"})
    json_spec["components"]["schemas"]["ProxySettingsXo"].update({"nullable": "true"})
    json_spec["paths"]["/v1/iq/verify-connection"]["post"]["operationId"] = (
        "verifyIqConnection"
    )
    json_spec["paths"]["/v1/iq/verify-connection"]["post"]["responses"]["200"][
        "content"
    ] = {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/IqConnectionVerificationXo"}
        }
    }
    json_spec["paths"]["/v1/repositories/terraform/proxy/{repositoryName}"]["get"][
        "responses"
    ]["200"]["content"] = {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/TerraformProxyApiRepository"}
        }
    }
    if "requestBody" not in json_spec["paths"]["/v1/components"]["post"]:
        json_spec["paths"]["/v1/components"]["post"]["requestBody"] = {
            "content": {"multipart/form-data": {"schema": {"properties": {}}}}
        }
    json_spec["paths"]["/v1/components"]["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]["properties"]["terraform.uploadType"] = {
        "description": "terraform Upload Type",
        "enum": ["module", "provider"],
        "type": "string",
    }
    json_spec["paths"]["/v1/tasks"]["post"]["responses"]["201"]["content"][
        "application/json"
    ] = {"schema": {"$ref": "#/components/schemas/TaskXO"}}
    json_spec["components"]["schemas"]["TerraformHostedRepositoryApiRequest"][
        "properties"
    ].update(
        {
            "format": {"type": "string", "default": "terraform"},
            "type": {"type": "string", "default": "hosted"},
            "url": {"type": "string"},
            "component": {"$ref": "#/components/schemas/ComponentAttributes"},
        }
    )
    json_spec["paths"]["/v1/repositories/terraform/hosted/{repositoryName}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"] = {
        "schema": {"$ref": "#/components/schemas/TerraformHostedRepositoryApiRequest"}
    }
    json_spec["paths"]["/v1/repositories/swift/proxy/{repositoryName}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"] = {
        "schema": {"$ref": "#/components/schemas/SwiftProxyApiRepository"}
    }


@progress_block("Patching licensed solution, Terraform proxy, and Yum schemas")
def patch_licensed_solution_terraform_proxy_and_yum(
    json_spec: dict, _nxrm_version: str
) -> None:
    if "Licensed Solution" in json_spec["components"]["schemas"]:
        json_spec["components"]["schemas"]["LicensedSolution"] = json_spec[
            "components"
        ]["schemas"]["Licensed Solution"]
        del json_spec["components"]["schemas"]["Licensed Solution"]
        json_spec["components"]["schemas"]["IqConnectionXo"]["properties"][
            "licensedSolutions"
        ]["items"]["$ref"] = "#/components/schemas/LicensedSolution"
    json_spec["components"]["schemas"]["TerraformProxyApiRepository"]["properties"][
        "terraform"
    ] = {"$ref": "#/components/schemas/TerraformAttributes"}
    for name, base, repo_type in (
        ("YumProxyApiRepository", "YumProxyRepositoryApiRequest", "proxy"),
        ("YumGroupApiRepository", "YumGroupRepositoryApiRequest", "group"),
    ):
        json_spec["components"]["schemas"][name] = {
            "allOf": [
                {"$ref": f"#/components/schemas/{base}"},
                {
                    "type": "object",
                    "required": ["format", "type", "url"],
                    "properties": {
                        "format": {"type": "string", "default": "yum"},
                        "type": {"type": "string", "default": repo_type},
                        "url": {"type": "string"},
                        **(
                            {
                                "routingRuleName": {
                                    "description": "The name of the routing rule assigned to this repository",
                                    "type": "string",
                                }
                            }
                            if repo_type == "proxy"
                            else {}
                        ),
                    },
                },
            ]
        }
        path = f"/v1/repositories/yum/{repo_type}/{{repositoryName}}"
        if "200" not in json_spec["paths"][path]["get"]["responses"]:
            json_spec["paths"][path]["get"]["responses"]["200"] = {
                "content": {"application/json": {}}
            }
        json_spec["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] = {"$ref": f"#/components/schemas/{name}"}


@progress_block("Patching Alpine schemas")
def patch_alpine_repositories(json_spec: dict, _nxrm_version: str) -> None:
    for repo_type, base in (
        ("hosted", "AlpineHostedRepositoryApiRequest"),
        ("proxy", "AlpineProxyRepositoryApiRequest"),
        ("group", "AlpineGroupRepositoryApiRequest"),
    ):
        name = f"Alpine{repo_type.capitalize()}ApiRepository"
        properties = {
            "format": {"type": "string", "default": "alpine"},
            "type": {"type": "string", "default": repo_type},
            "url": {"type": "string"},
        }
        if repo_type == "proxy":
            properties["routingRuleName"] = {
                "description": "The name of the routing rule assigned to this repository",
                "type": "string",
            }
        json_spec["components"]["schemas"][name] = {
            "allOf": [
                {"$ref": f"#/components/schemas/{base}"},
                {
                    "type": "object",
                    "required": ["format", "type", "url"],
                    "properties": properties,
                },
            ]
        }
        path = f"/v1/repositories/alpine/{repo_type}/{{repositoryName}}"
        if "200" not in json_spec["paths"][path]["get"]["responses"]:
            json_spec["paths"][path]["get"]["responses"]["200"] = {
                "content": {"application/json": {}}
            }
        json_spec["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] = {"$ref": f"#/components/schemas/{name}"}


PATCHES = [
    patch_info,
    patch_security,
    patch_repository_operation_ids,
    patch_privilege_operation_ids,
    patch_privilege_response_schemas,
    patch_storage_and_http_attributes,
    patch_selected_operation_ids,
    patch_ldap_schemas,
    patch_missing_success_responses,
    patch_input_stream_schema,
    patch_docker_pypi_and_writable_member_repositories,
    patch_raw_cargo_and_conan_repositories,
    patch_task_endpoints,
    patch_component_tag_proxy_nullable_iq_terraform_swift,
    patch_licensed_solution_terraform_proxy_and_yum,
    patch_alpine_repositories,
    add_missing_response_descriptions,
]


def apply_patches(json_spec: dict, nxrm_version: str) -> dict:
    for patch in PATCHES:
        patch(json_spec, nxrm_version)
    return json_spec


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <REPO_SERVER_URL>")
        sys.exit(0)
    json_spec, nxrm_version = load_spec(sys.argv[1])
    write_spec(apply_patches(json_spec, nxrm_version))


if __name__ == "__main__":
    main()
