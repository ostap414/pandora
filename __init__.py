"""
Reads vehicle status from BMW connected drive portal.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/bmw_connected_drive/
"""
import datetime
import logging

import voluptuous as vol

from homeassistant.const import (CONF_USERNAME, CONF_PASSWORD)
from homeassistant.helpers import discovery
from homeassistant.helpers.event import track_utc_time_change
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['bimmer_connected==0.5.3']

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'pandora'
CONF_READ_ONLY = 'read_only'
ATTR_ID = 'id'

ACCOUNT_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_READ_ONLY, default=False): cv.boolean,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: {
        cv.string: ACCOUNT_SCHEMA
    },
}, extra=vol.ALLOW_EXTRA)

SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ID): cv.string,
})


PANDORA_COMPONENTS = ['device_tracker', 'binary_sensor', 'sensor']

SERVICE_UPDATE_STATE = 'update_state'


_SERVICE_MAP = {
    'enable_seat_heater': 'trigger_remote_seat_heater',
}

def setup(hass, config: dict):
    """Set up the BMW connected drive components."""
    accounts = []
    for name, account_config in config[DOMAIN].items():
        accounts.append(setup_account(account_config, hass, name))

    hass.data[DOMAIN] = accounts

    def _update_all(call) -> None:
        """Update all pandora accounts."""
        for po_account in hass.data[DOMAIN]:
            po_account.update()

    # Service to manually trigger updates for all accounts.
    hass.services.register(DOMAIN, SERVICE_UPDATE_STATE, _update_all)

    _update_all(None)

    for component in PANDORA_COMPONENTS:
        discovery.load_platform(hass, component, DOMAIN, {}, config)

    return True


def setup_account(account_config: dict, hass, name: str) \
        -> 'PandoraOnlineAccount':
    """Set up a new BMWConnectedDriveAccount based on the config."""
    username = account_config[CONF_USERNAME]
    password = account_config[CONF_PASSWORD]
    read_only = account_config[CONF_READ_ONLY]

    _LOGGER.debug('Adding new account %s', name)
    po_account = PandoraOnlineAccount(username, password, name, read_only)

    def execute_service(call):
        """Execute a service for a vehicle.

        This must be a member function as we need access to the cd_account
        object here.
        """
        id = call.data[ATTR_ID]
        vehicle = po_account.account.get_vehicle(id)
        if not vehicle:
            _LOGGER.error('Could not find a vehicle for id "%s"!', id)
            return
        function_name = _SERVICE_MAP[call.service]
        function_call = getattr(vehicle.remote_services, function_name)
        function_call()

    # register the remote services
    for service in _SERVICE_MAP:
        hass.services.register(
            DOMAIN, service,
            execute_service,
            schema=SERVICE_SCHEMA)

    now = datetime.datetime.now()
    track_utc_time_change(
        hass, po_account.update,
        minute=range(0, 60, 1),
        second=now.second)

    return po_account


class PandoraOnlineAccount:
    """Representation of a Pandora Online vehicle."""

    def __init__(self, username: str, password: str,
                 name: str, read_only) -> None:
        """Constructor."""
        from .pandora_online.account import PandoraOnlineAccount

        self.read_only = read_only
        self.account = PandoraOnlineAccount(username, password)
        self.name = name
        self._update_listeners = []

    def update(self, *_):
        """Update the state of all vehicles.

        Notify all listeners about the update.
        """
        _LOGGER.debug('Updating vehicle state for account %s, '
                      'notifying %d listeners',
                      self.name, len(self._update_listeners))
        try:
            self.account.update_vehicle_states()
            for listener in self._update_listeners:
                listener()
        except IOError as exception:
            _LOGGER.error('Error updating the vehicle state.')
            _LOGGER.exception(exception)

    def add_update_listener(self, listener):
        """Add a listener for update notifications."""
        self._update_listeners.append(listener)
