from c3nav.mapdata.models.access import AccessPermission, AccessPermissionSSOGrant


def access_permissions(backend, response, user=None, *args, **kwargs):
    """Grant access permissions using group membership from provider."""
    if not user or (groups := response.get('groups')) is None:
        return

    # delete permissions granted to the user by groups they no longer are part of
    user.accesspermissions.filter(sso_grant__provider=backend.name).exclude(sso_grant__group__in=groups).delete()

    if not groups:
        return

    existing_grants = set(AccessPermission.objects.filter(sso_grant__provider=backend.name)
                          .values_list('sso_grant_id', flat=True))
    new_grants = AccessPermissionSSOGrant.objects.filter(provider=backend.name, group__in=groups) \
        .exclude(id__in=existing_grants)

    new_perms = []
    for grant in new_grants:
        new_perms.append(AccessPermission(
            user=user,
            access_restriction_id=grant.access_restriction_id,
            access_restriction_group_id=grant.access_restriction_group_id,
            sso_grant=grant
        ))
    if new_grants:
        AccessPermission.objects.bulk_create(new_perms)
