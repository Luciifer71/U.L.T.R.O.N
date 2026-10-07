"""Exact installed-app discovery while preserving legacy known aliases."""
from ultron_control.application_discovery import ApplicationDiscovery, ApplicationAmbiguous
from .catalog import name_key


class ExactApplicationDiscovery(ApplicationDiscovery):
    def _best_start_app_match(self, normalized, apps):
        matches = [(name, app_id) for name, app_id in apps if name_key(name) == name_key(normalized)]
        identities = {app_id for _, app_id in matches}
        if len(identities) > 1:
            raise ApplicationAmbiguous('Multiple installed applications have that exact name; specify the application identity.')
        return matches[0] if matches else None

    def _resolve_packaged_app(self, normalized, start_apps):
        exact_ids = {app_id for name, app_id in start_apps if name_key(name) == name_key(normalized)}
        matches = []
        for app in self.list_packaged_apps():
            identity = app.get('aumid') or f"{app.get('packageFamilyName', '')}!{app.get('applicationId', '')}"
            names = [app.get(key, '') for key in ('name', 'packageDisplayName', 'applicationDisplayName')]
            names.append(self._package_identity_name(app))
            if identity in exact_ids or any(name and not name.casefold().startswith('ms-resource:') and name_key(name) == name_key(normalized) for name in names):
                matches.append(app)
        identities = {(item.get('packageFamilyName'), item.get('applicationId')) for item in matches}
        if len(identities) > 1:
            raise ApplicationAmbiguous('Multiple packaged applications have that exact name; specify the application identity.')
        if not matches:
            return None
        selected = matches[0]
        identity = selected.get('aumid') or f"{selected['packageFamilyName']}!{selected['applicationId']}"
        display = next((name for name, app_id in start_apps if app_id == identity and name_key(name) == name_key(normalized)), self._friendly_packaged_name(selected))
        return self._packaged_result(requested_name=normalized, app=selected, display_name=display)
