from middlewared.api.current import PrivilegeRoleEntry

from middlewared.role import ROLES
from middlewared.service import Service, filterable_api_method, filter_list


class PrivilegeService(Service):

    class Config:
        namespace = "privilege"
        cli_namespace = "auth.privilege"

    @filterable_api_method(item=PrivilegeRoleEntry, authorization_required=False)
    async def roles(self, filters, options):
        """
        Get all available roles.

        Each entry contains the following keys:

        `name` - the internal name of the role

        `includes` - list of other roles that this role includes. When user is
        granted this role, they will also receive permissions granted by all
        the included roles.

        `builtin` - role exists for internal backend purposes for access
        control.
        """
        roles = [
            {
                "name": name,
                "title": name,
                "includes": role.includes,
                "builtin": role.builtin,
                "stig": role.stig,
            }
            for name, role in ROLES.items()
        ]

        return filter_list(roles, filters, options)
