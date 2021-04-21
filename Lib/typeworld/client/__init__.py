# -*- coding: utf-8 -*-

import os
import sys
import json
import copy
import platform
import urllib.request
import urllib.error
import urllib.parse
import traceback
import time
import base64
import threading
import ssl
import certifi
import semver
import logging
import inspect
import re
from time import gmtime, strftime
import requests
import requests.exceptions

import typeworld.api
from typeworld.api import VERSION

from typeworld.client.helpers import (
    ReadFromFile,
    WriteToFile,
    MachineName,
    addAttributeToURL,
    OSName,
    Garbage,
)

WIN = platform.system() == "Windows"
MAC = platform.system() == "Darwin"
LINUX = platform.system() == "Linux"
CI = os.getenv("CI", "false").lower() == "true"
GAE = os.getenv("GAE_ENV", "").startswith("standard")

MOTHERSHIP = "https://api.type.world/v1"

if MAC:
    from AppKit import NSUserDefaults
    from typeworld.client.helpers import nslog


class DummyKeyring(object):
    def __init__(self):
        self.passwords = {}

    def set_password(self, key, username, password):
        self.passwords[(key, username)] = password

    def get_password(self, key, username):
        if (key, username) in self.passwords:
            return self.passwords[(key, username)]

    def delete_password(self, key, username):
        if (key, username) in self.passwords:
            del self.passwords[(key, username)]


dummyKeyRing = DummyKeyring()
if "TRAVIS" in os.environ:
    import tempfile

    tempFolder = tempfile.mkdtemp()


def urlIsValid(url):

    if (
        not url.find("typeworld://")
        < url.find("+")
        < url.find("http")
        < url.find("//", url.find("http"))
    ):
        return False, "URL is malformed."

    if url.count("@") > 1:
        return (
            False,
            "URL contains more than one @ sign, so don’t know how to parse it.",
        )

    found = False
    for protocol in typeworld.api.PROTOCOLS:
        if url.startswith(protocol + "://"):
            found = True
            break
    if not found:
        return (
            False,
            "Unknown custom protocol, known are: %s" % (typeworld.api.PROTOCOLS),
        )

    if url.count("://") > 1:
        return (
            False,
            (
                "URL contains more than one :// combination, "
                "so don’t know how to parse it."
            ),
        )

    return True, None


class URL(object):
    def __init__(self, url):
        (
            self.customProtocol,
            self.protocol,
            self.transportProtocol,
            self.subscriptionID,
            self.secretKey,
            self.accessToken,
            self.restDomain,
        ) = splitJSONURL(url)

    def unsecretURL(self):

        if self.subscriptionID and self.secretKey:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.subscriptionID)
                + ":"
                + "secretKey"
                + "@"
                + str(self.restDomain)
            )

        elif self.subscriptionID:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.subscriptionID)
                + "@"
                + str(self.restDomain)
            )

        else:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.restDomain)
            )

    def shortUnsecretURL(self):

        if self.subscriptionID:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.subscriptionID)
                + "@"
                + str(self.restDomain)
            )

        else:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.restDomain)
            )

    def secretURL(self):

        if self.subscriptionID and self.secretKey:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.subscriptionID)
                + ":"
                + str(self.secretKey)
                + "@"
                + str(self.restDomain)
            )

        elif self.subscriptionID:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.subscriptionID)
                + "@"
                + str(self.restDomain)
            )

        else:
            return (
                str(self.customProtocol)
                + str(self.protocol)
                + "+"
                + str(self.transportProtocol.replace("://", "//"))
                + str(self.restDomain)
            )

    def HTTPURL(self):
        return str(self.transportProtocol) + str(self.restDomain)


def getProtocol(url):

    protocolName = URL(url).protocol

    for ext in (".py", ".pyc"):
        if os.path.exists(
            os.path.join(os.path.dirname(__file__), "protocols", protocolName + ext)
        ):

            import importlib

            spec = importlib.util.spec_from_file_location(
                "json",
                os.path.join(
                    os.path.dirname(__file__), "protocols", protocolName + ext
                ),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            protocolObject = module.TypeWorldProtocol(url)

            return True, protocolObject

    return False, "Protocol %s doesn’t exist in this app (yet)." % protocolName


def request(url, parameters={}, method="POST"):
    """Perform request in a loop 10 times, because the central server’s instance might
    shut down unexpectedly during a request, especially longer running ones."""

    message = None

    for i in range(10):
        try:
            if method == "POST":
                response = requests.post(url, parameters, timeout=30)
            elif method == "GET":
                response = requests.get(url, timeout=30)
        # except requests.exceptions.ConnectionError:
        #     message = f'Connection refused: {url}'
        # except requests.exceptions.HTTPError:
        #     message = f'HTTP Error: {url}'
        # except requests.exceptions.Timeout:
        #     message = f'Connection timed out: {url}'
        # except requests.exceptions.TooManyRedirects:
        #     message = f'Too many redirects: {url}'
        except Exception:
            if parameters:
                parameters = copy.copy(parameters)
                for key in parameters:
                    if key.lower().endswith("key"):
                        parameters[key] = "*****"
                    if key.lower().endswith("secret"):
                        parameters[key] = "*****"
                message = (
                    f"Response from {url} with parameters "
                    f"{parameters} after {i+1} tries: "
                    + traceback.format_exc().splitlines()[-1]
                )
            else:
                message = traceback.format_exc().splitlines()[-1]
            return False, message, None
        else:
            # try:
            if response.status_code != 200:
                return False, f"HTTP Error {response.status_code}", response

            else:
                return True, response.content, response


def splitJSONURL(url):

    customProtocol = "typeworld://"
    url = url.replace(customProtocol, "")

    protocol = url.split("+")[0]
    url = url.replace(protocol + "+", "")

    url = url.replace("http//", "http://")
    url = url.replace("https//", "https://")
    url = url.replace("HTTP//", "http://")
    url = url.replace("HTTPS//", "https://")

    transportProtocol = None
    if url.startswith("https://"):
        transportProtocol = "https://"
    elif url.startswith("http://"):
        transportProtocol = "http://"

    urlRest = url[len(transportProtocol) :]

    subscriptionID = ""
    secretKey = ""
    accessToken = ""

    # With credentials
    if "@" in urlRest:

        credentials, domain = urlRest.split("@")
        credentialParts = credentials.split(":")

        if len(credentialParts) == 3:
            subscriptionID, secretKey, accessToken = credentialParts

        elif len(credentialParts) == 2:
            subscriptionID, secretKey = credentialParts

        elif len(credentialParts) == 1:
            subscriptionID = credentialParts[0]

    # No credentials given
    else:
        domain = urlRest

    return (
        customProtocol,
        protocol,
        transportProtocol,
        subscriptionID,
        secretKey,
        accessToken,
        domain,
    )


class Preferences(object):
    def __init__(self):
        self._dict = {}  # nocoverage
        # (In tests, preferences are loaded either as JSON or as AppKitNSUserDefaults,
        # not the plain class here)

    def get(self, key):
        if key in self._dict:
            return self._dict[key]

    def set(self, key, value):
        self._dict[key] = value
        self.save()

    def remove(self, key):
        if key in self._dict:
            del self._dict[key]

    def save(self):
        pass

    def dictionary(self):
        return self._dict  # nocoverage
        # (In tests, preferences are loaded either as JSON or as AppKitNSUserDefaults,
        # not the plain class here)


class JSON(Preferences):
    def __init__(self, path):
        self.path = path
        self._dict = {}

        if self.path and os.path.exists(self.path):
            self._dict = json.loads(ReadFromFile(self.path))

    def save(self):

        if not os.path.exists(os.path.dirname(self.path)):
            os.makedirs(os.path.dirname(self.path))
        WriteToFile(self.path, json.dumps(self._dict))

    def dictionary(self):
        return self._dict


class AppKitNSUserDefaults(Preferences):
    def __init__(self, name):
        # 		NSUserDefaults = objc.lookUpClass('NSUserDefaults')
        self.defaults = NSUserDefaults.alloc().initWithSuiteName_(name)
        self.values = {}

    def get(self, key):

        if key in self.values:
            return self.values[key]

        else:

            o = self.defaults.objectForKey_(key)

            if o:

                if "Array" in o.__class__.__name__:
                    o = list(o)

                elif "Dictionary" in o.__class__.__name__:
                    o = dict(o)

                elif "unicode" in o.__class__.__name__:
                    o = str(o)

                self.values[key] = o
                return self.values[key]

    def set(self, key, value):

        # 		self.defaults.setObject_forKey_(json.dumps(value), key)

        # if MAC:
        # 	if type(value) == dict:
        # 		value = NSDictionary.alloc().initWithDictionary_(value)

        self.values[key] = value
        self.defaults.setObject_forKey_(value, key)

    def remove(self, key):
        if key in self.values:
            del self.values[key]

        if self.defaults.objectForKey_(key):
            self.defaults.removeObjectForKey_(key)

    def convertItem(self, item):

        if "Array" in item.__class__.__name__ or type(item) in (list, tuple):
            _list = list(item)
            for i, _item in enumerate(_list):
                _list[i] = self.convertItem(_item)
            return _list

        elif "Dictionary" in item.__class__.__name__ or type(item) == dict:
            d = dict(item)
            for k, v in d.items():
                d[k] = self.convertItem(v)

            return d

        elif "unicode" in item.__class__.__name__:
            return str(item)

    def dictionary(self):

        d = self.defaults.dictionaryRepresentation()
        return self.convertItem(d)


class TypeWorldClientDelegate(object):
    def __init__(self):
        self.client = None
        self.initialize()

    def initialize(self):
        pass

    def _fontWillInstall(self, font):
        try:
            self.fontWillInstall(font)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def fontWillInstall(self, font):
        assert type(font) == typeworld.api.Font

    def _fontHasInstalled(self, success, message, font):
        try:
            self.fontHasInstalled(success, message, font)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def fontHasInstalled(self, success, message, font):
        if success:
            assert type(font) == typeworld.api.Font

    def _fontWillUninstall(self, font):
        try:
            self.fontWillUninstall(font)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def fontWillUninstall(self, font):
        assert type(font) == typeworld.api.Font

    def _fontHasUninstalled(self, success, message, font):
        try:
            self.fontHasUninstalled(success, message, font)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def fontHasUninstalled(self, success, message, font):
        if success:
            assert type(font) == typeworld.api.Font

    def _subscriptionUpdateNotificationHasBeenReceived(self, subscription):
        try:
            self.subscriptionUpdateNotificationHasBeenReceived(subscription)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def subscriptionUpdateNotificationHasBeenReceived(self, subscription):
        assert type(subscription) == typeworld.client.APISubscription
        pass

    # def _subscriptionInvitationHasBeenReceived(self, invitation):
    #     try:
    #         self.subscriptionInvitationHasBeenReceived(invitation)
    #     except Exception:  # nocoverage
    #         self.client.handleTraceback(  # nocoverage
    #             sourceMethod=getattr(self, sys._getframe().f_code.co_name)
    #         )

    # def subscriptionInvitationHasBeenReceived(self, invitation):
    #     pass

    def _userAccountUpdateNotificationHasBeenReceived(self):
        try:
            self.userAccountUpdateNotificationHasBeenReceived()
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def userAccountUpdateNotificationHasBeenReceived(self):
        pass

    def _userAccountHasBeenUpdated(self):
        try:
            self.userAccountHasBeenUpdated()
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def userAccountHasBeenUpdated(self):
        pass

    def _subscriptionHasBeenDeleted(self, subscription):
        try:
            self.subscriptionHasBeenDeleted(subscription)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def subscriptionHasBeenDeleted(self, subscription):
        pass

    def _publisherHasBeenDeleted(self, publisher):
        try:
            self.publisherHasBeenDeleted(publisher)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def publisherHasBeenDeleted(self, publisher):
        pass

    def _subscriptionHasBeenAdded(self, subscription):
        try:
            self.subscriptionHasBeenAdded(subscription)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def subscriptionHasBeenAdded(self, subscription):
        pass

    def _subscriptionWillUpdate(self, subscription):
        try:
            self.subscriptionWillUpdate(subscription)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def subscriptionWillUpdate(self, subscription):
        pass

    def _subscriptionHasBeenUpdated(self, subscription, success, message, changes):
        try:
            self.subscriptionHasBeenUpdated(subscription, success, message, changes)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def subscriptionHasBeenUpdated(self, subscription, success, message, changes):
        pass

    def _clientPreferenceChanged(self, key, value):
        try:
            self.clientPreferenceChanged(key, value)
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def clientPreferenceChanged(self, key, value):
        pass

    def _messageQueueConnected(self):
        try:
            self.messageQueueConnected()
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def messageQueueConnected(self):
        pass

    def _messageQueueDisconnected(self):
        try:
            self.messageQueueDisconnected()
        except Exception:  # nocoverage
            self.client.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def messageQueueDisconnected(self):
        pass


class APIInvitation(object):
    keywords = ()

    def __init__(self, d):
        for key in self.keywords:
            # if key in d:
            setattr(self, key, d[key])
            # else:
            # 	setattr(self, key, None)


class APIPendingInvitation(APIInvitation):
    keywords = (
        "url",
        "ID",
        "invitedByUserName",
        "invitedByUserEmail",
        "time",
        "canonicalURL",
        "publisherName",
        "subscriptionName",
        "logoURL",
        "backgroundColor",
        "fonts",
        "families",
        "foundries",
        "websiteURL",
    )

    def accept(self):
        return self.parent.acceptInvitation(self.url)

    def decline(self):
        return self.parent.declineInvitation(self.url)


class APIAcceptedInvitation(APIInvitation):
    keywords = (
        "url",
        "ID",
        "invitedByUserName",
        "invitedByUserEmail",
        "time",
        "canonicalURL",
        "publisherName",
        "subscriptionName",
        "logoURL",
        "backgroundColor",
        "fonts",
        "families",
        "foundries",
        "websiteURL",
    )


class APISentInvitation(APIInvitation):
    keywords = (
        "url",
        "invitedUserName",
        "invitedUserEmail",
        "invitedTime",
        "acceptedTime",
        "confirmed",
    )


class APIClient(object):
    """\
    Main Type.World client app object.
    Use it to load repositories and install/uninstall fonts.
    """

    def __init__(
        self,
        preferences=None,
        secretTypeWorldAPIKey=None,
        delegate=None,
        mothership=None,
        mode="headless",
        zmqSubscriptions=False,
        online=False,
        testing=False,
        externallyControlled=False,
        secretServerAuthKey=None,
        inCompiledApp=False,
        commercial=False,
        appID="world.type.headless",
    ):

        try:
            self._preferences = preferences or Preferences()
            # if self:
            # 	self.clearPendingOnlineCommands()
            self._publishers = {}
            self._subscriptionsUpdated = []
            self.onlineCommandsQueue = []
            self._syncProblems = []
            self.secretTypeWorldAPIKey = secretTypeWorldAPIKey
            self.delegate = delegate or TypeWorldClientDelegate()
            self.delegate.client = self
            self.mothership = mothership or MOTHERSHIP
            self.mode = mode  # gui or headless
            self.zmqSubscriptions = zmqSubscriptions
            self._isSetOnline = online
            self.lastOnlineCheck = {}
            self.testing = testing
            self.externallyControlled = externallyControlled
            self.secretServerAuthKey = secretServerAuthKey
            self.inCompiledApp = inCompiledApp
            self.commercial = commercial
            self.appID = appID

            self._zmqRunning = False
            self._zmqCallbacks = {}

            self.sslcontext = ssl.create_default_context(cafile=certifi.where())

            # For Unit Testing
            self.testScenario = None

            self._systemLocale = None
            self._online = {}

            # wentOnline()
            if self._isSetOnline:
                self.wentOnline()

            # ZMQ
            if self._isSetOnline and self.zmqSubscriptions:
                if self.user():
                    topicID = "user-%s" % self.user()
                    self.registerZMQCallback(topicID, self.zmqCallback)
                self.manageMessageQueueConnection()

        except Exception as e:  # nocoverage
            self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def __repr__(self):
        return f'<APIClient user="{self.user()}">'

    def tracebackTest(self):
        try:
            assert abc  # noqa: F821

        except Exception as e:
            self.handleTraceback(
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def tracebackTest2(self):
        try:
            assert abc  # noqa: F821

        except Exception:
            self.handleTraceback(
                sourceMethod=getattr(self, sys._getframe().f_code.co_name)
            )

    def wentOnline(self):
        success, message = self.downloadSettings(performCommands=True)
        assert success
        assert self.get("downloadedSettings")["messagingQueue"].startswith("tcp://")
        assert self.get("downloadedSettings")["breakingAPIVersions"]

    def wentOffline(self):
        pass

    def zmqSetup(self):
        import zmq
        import zmq.error

        if not self._zmqRunning:
            self._zmqctx = zmq.Context.instance()
            self.zmqSocket = self._zmqctx.socket(zmq.SUB)

            # https://github.com/zeromq/libzmq/issues/2882
            self.zmqSocket.setsockopt(zmq.TCP_KEEPALIVE, 1)
            self.zmqSocket.setsockopt(zmq.TCP_KEEPALIVE_CNT, 10)
            self.zmqSocket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)
            self.zmqSocket.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 30)

            target = self.get("downloadedSettings")["messagingQueue"]
            self.zmqSocket.connect(target)

            self._zmqRunning = True
            self.zmqListenerThread = threading.Thread(
                target=self.zmqListener, daemon=True
            )
            self.zmqListenerThread.start()
            self.delegate._messageQueueConnected()

    def zmqListener(self):
        import zmq
        import zmq.error

        while self._zmqRunning:
            time.sleep(0.1)
            try:
                topic, msg = self.zmqSocket.recv_multipart(flags=zmq.NOBLOCK)
                topic = topic.decode()
                msg = msg.decode()

                if topic in self._zmqCallbacks:
                    self._zmqCallbacks[topic](msg)
            except zmq.Again:
                pass
            except zmq.error.ZMQError:
                pass

    def quit(self):
        self.zmqQuit()

    def zmqQuit(self):
        if self._zmqRunning:
            # for topic in self._zmqCallbacks:
            #     self.zmqSocket.setsockopt(zmq.UNSUBSCRIBE, topic.encode("ascii"))
            self._zmqRunning = False
            self.zmqSocket.close()
            self._zmqctx.destroy()
            self.zmqListenerThread.join()
            # self._zmqctx.term()
            self.delegate._messageQueueDisconnected()

    def registerZMQCallback(self, topic, method):
        import zmq
        import zmq.error

        if self.zmqSubscriptions:
            if self._zmqRunning and not self.zmqSocket.closed:
                self.zmqSocket.setsockopt(zmq.SUBSCRIBE, topic.encode("ascii"))
            self._zmqCallbacks[topic] = method

    def unregisterZMQCallback(self, topic):
        import zmq
        import zmq.error

        if self.zmqSubscriptions:
            if topic in self._zmqCallbacks:
                if self._zmqRunning and not self.zmqSocket.closed:
                    self.zmqSocket.setsockopt(zmq.UNSUBSCRIBE, topic.encode("ascii"))
                del self._zmqCallbacks[topic]

    def zmqCallback(self, message):
        try:

            if message:
                data = json.loads(message)
                if data["command"] == "pullUpdates" and (
                    "sourceAnonymousAppID" not in data
                    or (
                        "sourceAnonymousAppID" in data
                        and data["sourceAnonymousAppID"]
                        and data["sourceAnonymousAppID"] != self.anonymousAppID()
                    )
                ):
                    self.delegate._userAccountUpdateNotificationHasBeenReceived()

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    # def clearPendingOnlineCommands(self):
    # 	commands = self.get('pendingOnlineCommands') or {}
    # 	commands['acceptInvitation'] = []
    # 	commands['declineInvitation'] = []
    # 	commands['downloadSubscriptions'] = []
    # 	commands['linkUser'] = []
    # 	commands['syncSubscriptions'] = []
    # 	commands['unlinkUser'] = []
    # 	commands['uploadSubscriptions'] = []
    # 	self.set('pendingOnlineCommands', commands)

    def holdsSubscriptionWithLiveNotifcations(self):
        for publisher in self.publishers():
            for subscription in publisher.subscriptions():
                success, command = subscription.protocol.endpointCommand()
                if success:
                    if command.sendsLiveNotifications:
                        return True
        return False

    def requiresMessageQueueConnection(self):
        return (
            (self.user() and self.get("userAccountStatus") == "pro")
            or self.holdsSubscriptionWithLiveNotifcations()
            or self.testing
            # or self.testScenario == "simulateProAccount"
        )

    def manageMessageQueueConnection(self):
        import zmq
        import zmq.error

        if self._isSetOnline and self.zmqSubscriptions:
            requiresMessageQueueConnection = self.requiresMessageQueueConnection()

            if requiresMessageQueueConnection and not self._zmqRunning:
                self.zmqSetup()
                for topic in self._zmqCallbacks:
                    self.zmqSocket.setsockopt(zmq.SUBSCRIBE, topic.encode("ascii"))

            elif not requiresMessageQueueConnection and self._zmqRunning:
                self.zmqQuit()

    def get(self, key):
        try:
            return self._preferences.get(
                "world.type.guiapp." + key
            ) or self._preferences.get(key)
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def set(self, key, value):
        try:
            self._preferences.set("world.type.guiapp." + key, value)
            self.delegate._clientPreferenceChanged(key, value)
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def remove(self, key):
        try:
            self._preferences.remove("world.type.guiapp." + key)
            self._preferences.remove(key)
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performRequest(self, url, parameters={}, method="POST"):

        try:
            parameters["sourceAnonymousAppID"] = self.anonymousAppID()
            parameters["clientVersion"] = VERSION
            if self.testScenario == "simulateFaultyClientVersion":
                parameters["clientVersion"] = "abc"
            elif self.testScenario == "simulateNoClientVersion":
                del parameters["clientVersion"]

            if self.testing:
                parameters["testing"] = "true"

            # if self._isSetOnline:
            if self.testScenario:
                parameters["testScenario"] = self.testScenario
            if self.testScenario == "simulateCentralServerNotReachable":
                url = "https://api.type.worlddd/api"
            return request(url, parameters, method)
            # else:
            # 	return False, 'APIClient is set to work offline as set by:
            # APIClient(online=False)'

        except Exception as e:  # nocoverage
            success, message = self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )
            return success, message, None

    def pendingInvitations(self):
        try:
            _list = []
            if self.get("pendingInvitations"):
                for invitation in self.get("pendingInvitations"):
                    invitation = APIPendingInvitation(invitation)
                    invitation.parent = self
                    _list.append(invitation)
            return _list
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def acceptedInvitations(self):
        try:
            _list = []
            if self.get("acceptedInvitations"):
                for invitation in self.get("acceptedInvitations"):
                    invitation = APIAcceptedInvitation(invitation)
                    invitation.parent = self
                    _list.append(invitation)
            return _list
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def sentInvitations(self):
        try:
            _list = []
            if self.get("sentInvitations"):
                for invitation in self.get("sentInvitations"):
                    invitation = APISentInvitation(invitation)
                    invitation.parent = self
                    _list.append(invitation)
            return _list
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def secretSubscriptionURLs(self):
        try:

            _list = []

            for publisher in self.publishers():
                for subscription in publisher.subscriptions():
                    _list.append(subscription.protocol.secretURL())

            return _list

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def unsecretSubscriptionURLs(self):
        try:
            _list = []

            for publisher in self.publishers():
                for subscription in publisher.subscriptions():
                    _list.append(subscription.protocol.unsecretURL())

            return _list
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def timezone(self):
        try:
            return strftime("%z", gmtime())
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def syncProblems(self):
        return self._syncProblems

    def addMachineIDToParameters(self, parameters):
        try:
            (
                machineModelIdentifier,
                machineHumanReadableName,
                machineSpecsDescription,
            ) = MachineName()

            if machineModelIdentifier:
                parameters["machineModelIdentifier"] = machineModelIdentifier

            if machineHumanReadableName:
                parameters["machineHumanReadableName"] = machineHumanReadableName

            if machineSpecsDescription:
                parameters["machineSpecsDescription"] = machineSpecsDescription

            import platform

            parameters["machineNodeName"] = platform.node()

            osName = OSName()
            if osName:
                parameters["machineOSVersion"] = osName

            return parameters

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def online(self, server=None):
        try:

            if self.testScenario == "simulateNotOnline":
                return False

            if "GAE_DEPLOYMENT_ID" in os.environ:
                return True  # nocoverage

            if not server:
                server = "type.world"

            if not server.startswith("http"):
                server = "http://" + server

            if (
                server in self.lastOnlineCheck
                and type(self.lastOnlineCheck[server]) is float
            ):
                if time.time() - self.lastOnlineCheck[server] < 10:
                    return True

            try:
                urllib.request.urlopen(server, context=self.sslcontext)  # Python 3.x
            except urllib.error.URLError:
                return False
            # Do nothing if HTTP errors are returned, and let the subsequent methods
            # handle the details
            except urllib.error.HTTPError:
                pass

            self.lastOnlineCheck[server] = time.time()
            return True

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def appendCommands(self, commandName, commandsList=["pending"]):
        try:

            # Set up data structure
            commands = self.get("pendingOnlineCommands")
            if not self.get("pendingOnlineCommands"):
                commands = {}
            # Init empty
            if commandName not in commands:
                commands[commandName] = []
            if (
                commandName in commands and len(commands[commandName]) == 0
            ):  # set anyway if empty because NSObject immutability
                commands[commandName] = []
            self.set("pendingOnlineCommands", commands)

            # Add commands to list
            commands = self.get("pendingOnlineCommands")
            if type(commandsList) in (str, int):
                commandsList = [commandsList]
            for commandListItem in commandsList:
                if commandListItem not in commands[commandName]:
                    commands[commandName] = list(commands[commandName])
                    commands[commandName].append(commandListItem)
            self.set("pendingOnlineCommands", commands)

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performCommands(self):
        try:

            success, message = True, None
            self._syncProblems = []

            if self.online():

                commands = self.get("pendingOnlineCommands") or {}

                if "unlinkUser" in commands and commands["unlinkUser"]:
                    success, message = self.performUnlinkUser()

                    if success:
                        commands["unlinkUser"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if "linkUser" in commands and commands["linkUser"]:
                    success, message = self.performLinkUser(commands["linkUser"][0])

                    if success:
                        commands["linkUser"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if "syncSubscriptions" in commands and commands["syncSubscriptions"]:
                    success, message = self.performSyncSubscriptions(
                        commands["syncSubscriptions"]
                    )

                    if success:
                        commands["syncSubscriptions"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if (
                    "uploadSubscriptions" in commands
                    and commands["uploadSubscriptions"]
                ):
                    success, message = self.perfomUploadSubscriptions(
                        commands["uploadSubscriptions"]
                    )

                    if success:
                        commands["uploadSubscriptions"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if "acceptInvitation" in commands and commands["acceptInvitation"]:
                    success, message = self.performAcceptInvitation(
                        commands["acceptInvitation"]
                    )

                    if success:
                        commands["acceptInvitation"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if "declineInvitation" in commands and commands["declineInvitation"]:
                    success, message = self.performDeclineInvitation(
                        commands["declineInvitation"]
                    )

                    if success:
                        commands["declineInvitation"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if (
                    "downloadSubscriptions" in commands
                    and commands["downloadSubscriptions"]
                ):
                    success, message = self.performDownloadSubscriptions()

                    if success:
                        commands["downloadSubscriptions"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if "downloadSettings" in commands and commands["downloadSettings"]:
                    success, message = self.performDownloadSettings()

                    if success:
                        commands["downloadSettings"] = []
                        self.set("pendingOnlineCommands", commands)

                    else:
                        self._syncProblems.append(message)

                if self._syncProblems:
                    return False, self._syncProblems[0]
                else:
                    return True, None

            else:

                self._syncProblems.append("#(response.notOnline)")
                return (
                    False,
                    ["#(response.notOnline)", "#(response.notOnline.headline)"],
                )

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def uploadSubscriptions(self, performCommands=True):
        try:

            self.appendCommands(
                "uploadSubscriptions", self.secretSubscriptionURLs() or ["empty"]
            )
            self.appendCommands("downloadSubscriptions")

            success, message = True, None
            if performCommands:
                success, message = self.performCommands()
            return success, message

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def perfomUploadSubscriptions(self, oldURLs):

        try:

            userID = self.user()

            if userID:

                if oldURLs == ["pending"]:
                    oldURLs = ["empty"]

                self.set("lastServerSync", int(time.time()))

                # 				self.log('Uploading subscriptions: %s' % oldURLs)

                parameters = {
                    "anonymousAppID": self.anonymousAppID(),
                    "anonymousUserID": userID,
                    "subscriptionURLs": ",".join(oldURLs),
                    "secretKey": self.secretKey(),
                }

                success, response, responseObject = self.performRequest(
                    self.mothership + "/uploadUserSubscriptions", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

            # Success
            return True, None
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def downloadSubscriptions(self, performCommands=True):

        try:
            if self.user():
                self.appendCommands("downloadSubscriptions")

                if performCommands:
                    return self.performCommands()
            else:
                return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performDownloadSubscriptions(self):
        try:
            userID = self.user()

            if userID:

                parameters = {
                    "anonymousAppID": self.anonymousAppID(),
                    "anonymousUserID": userID,
                    "userTimezone": self.timezone(),
                    "secretKey": self.secretKey(),
                }

                success, response, responseObject = self.performRequest(
                    self.mothership + "/downloadUserSubscriptions", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

                self.set("lastServerSync", int(time.time()))

                return self.executeDownloadSubscriptions(response)

            return True, None
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def executeDownloadSubscriptions(self, response):
        try:
            oldURLs = self.secretSubscriptionURLs()

            # Uninstall all protected fonts when app instance is reported as revoked
            if response["appInstanceIsRevoked"]:
                success, message = self.uninstallAllProtectedFonts()
                if not success:
                    return False, message

            # Verified Email Address
            if "userAccountEmailIsVerified" in response:
                self.set(
                    "userAccountEmailIsVerified", response["userAccountEmailIsVerified"]
                )

            # USer Account Status
            if "userAccountStatus" in response:
                self.set("userAccountStatus", response["userAccountStatus"])

            # Website Token
            if "typeWorldWebsiteToken" in response:
                keyring = self.keyring()
                keyring.set_password(
                    self.userKeychainKey(self.user()),
                    "typeWorldWebsiteToken",
                    response["typeWorldWebsiteToken"],
                )

            # Add new subscriptions
            for incomingSubscription in response["heldSubscriptions"]:

                # Incoming server timestamp
                incomingServerTimestamp = None
                if (
                    "serverTimestamp" in incomingSubscription
                    and incomingSubscription["serverTimestamp"]
                ):
                    incomingServerTimestamp = incomingSubscription["serverTimestamp"]

                # Add new subscription
                if incomingSubscription["url"] not in oldURLs:
                    success, message, publisher, subscription = self.addSubscription(
                        incomingSubscription["url"], updateSubscriptionsOnServer=False
                    )

                    if success:

                        if incomingServerTimestamp:
                            subscription.set("serverTimestamp", incomingServerTimestamp)

                        self.delegate._subscriptionHasBeenAdded(subscription)

                    else:
                        return (
                            False,
                            "Received from self.addSubscription() for %s: %s"
                            % (incomingSubscription["url"], message),
                        )

                # Update subscription
                else:
                    subscription = None
                    for publisher in self.publishers():
                        for subscription in publisher.subscriptions():
                            if (
                                subscription.url
                                == URL(incomingSubscription["url"]).unsecretURL()
                            ):
                                break

                    if (
                        incomingServerTimestamp
                        and subscription.get("serverTimestamp")
                        and int(incomingServerTimestamp)
                        > int(subscription.get("serverTimestamp"))
                    ) or (
                        incomingServerTimestamp
                        and not subscription.get("serverTimestamp")
                    ):
                        success, message, changes = subscription.update()

                        if success:
                            subscription.set(
                                "serverTimestamp", int(incomingServerTimestamp)
                            )

            def replace_item(obj, key, replace_value):
                for k, v in obj.items():
                    if v == key:
                        obj[k] = replace_value
                return obj

            # oldPendingInvitations = self.pendingInvitations()

            # Invitations
            self.set(
                "acceptedInvitations",
                [replace_item(x, None, "") for x in response["acceptedInvitations"]],
            )
            self.set(
                "pendingInvitations",
                [replace_item(x, None, "") for x in response["pendingInvitations"]],
            )
            self.set(
                "sentInvitations",
                [replace_item(x, None, "") for x in response["sentInvitations"]],
            )

            # newPendingInvitations = self.pendingInvitations()
            # TODO: trigger notification

            # import threading
            # preloadThread = threading.Thread(target=self.preloadLogos)
            # preloadThread.start()

            # Delete subscriptions
            for publisher in self.publishers():
                for subscription in publisher.subscriptions():
                    if not subscription.protocol.secretURL() in [
                        x["url"] for x in response["heldSubscriptions"]
                    ]:
                        subscription.delete(updateSubscriptionsOnServer=False)

            self.delegate._userAccountHasBeenUpdated()

            return True, None
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def acceptInvitation(self, url):
        try:
            userID = self.user()
            if userID:
                self.appendCommands("acceptInvitation", [url])

            return self.performCommands()
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performAcceptInvitation(self, urls):
        try:
            userID = self.user()

            # Get Invitation IDs from urls
            IDs = []
            for invitation in self.pendingInvitations():
                for url in urls:
                    if invitation.url == url:
                        if invitation.ID not in IDs:
                            IDs.append(invitation.ID)
            assert len(IDs) == len(urls)

            if userID:

                self.set("lastServerSync", int(time.time()))

                parameters = {
                    "anonymousAppID": self.anonymousAppID(),
                    "anonymousUserID": userID,
                    "subscriptionIDs": ",".join(IDs),
                    "secretKey": self.secretKey(),
                }

                success, response, responseObject = self.performRequest(
                    self.mothership + "/acceptInvitations", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

                # Success
                return self.executeDownloadSubscriptions(response)
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def declineInvitation(self, url):
        try:

            userID = self.user()
            if userID:
                self.appendCommands("declineInvitation", [url])

            return self.performCommands()

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performDeclineInvitation(self, urls):
        try:
            userID = self.user()

            # Get Invitation IDs from urls
            IDs = []
            for invitation in self.pendingInvitations():
                for url in urls:
                    if invitation.url == url:
                        if invitation.ID not in IDs:
                            IDs.append(invitation.ID)
            assert len(IDs) == len(urls)

            if userID:

                self.set("lastServerSync", int(time.time()))

                parameters = {
                    "anonymousAppID": self.anonymousAppID(),
                    "anonymousUserID": userID,
                    "subscriptionIDs": ",".join(IDs),
                    "secretKey": self.secretKey(),
                }

                success, response, responseObject = self.performRequest(
                    self.mothership + "/declineInvitations", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

                # Success
                return self.executeDownloadSubscriptions(response)
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def syncSubscriptions(self, performCommands=True):
        try:
            self.appendCommands(
                "syncSubscriptions", self.secretSubscriptionURLs() or ["empty"]
            )

            if performCommands:
                return self.performCommands()
            else:
                return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performSyncSubscriptions(self, oldURLs):
        try:
            userID = self.user()

            if userID:

                if oldURLs == ["pending"]:
                    oldURLs = ["empty"]

                self.set("lastServerSync", int(time.time()))

                parameters = {
                    "anonymousAppID": self.anonymousAppID(),
                    "anonymousUserID": userID,
                    "subscriptionURLs": ",".join(oldURLs),
                    "secretKey": self.secretKey(),
                }

                success, response, responseObject = self.performRequest(
                    self.mothership + "/syncUserSubscriptions", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

                # Add new subscriptions
                for url in response["subscriptions"]:
                    if url not in oldURLs:
                        (
                            success,
                            message,
                            publisher,
                            subscription,
                        ) = self.addSubscription(url, updateSubscriptionsOnServer=False)

                        if not success:
                            return False, message

                # Success
                return True, len(response["subscriptions"]) - len(oldURLs)

            return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def downloadSettings(self, performCommands=True):

        try:

            if performCommands:
                return self.performDownloadSettings()
            else:
                self.appendCommands("downloadSettings")

            return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performDownloadSettings(self):
        try:

            parameters = {}

            if self.user():
                parameters["anonymousUserID"] = self.user()
                parameters["secretKey"] = self.secretKey()

            success, response, responseObject = self.performRequest(
                self.mothership + "/downloadSettings", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            self.set("downloadedSettings", response["settings"])
            self.set("lastSettingsDownloaded", int(time.time()))

            return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def user(self):
        try:
            return self.get("typeworldUserAccount") or ""
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def userKeychainKey(self, ID):
        try:
            return "https://%s@%s.type.world" % (ID, self.anonymousAppID())
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def secretKey(self, userID=None):
        try:
            keyring = self.keyring()
            return keyring.get_password(
                self.userKeychainKey(userID or self.user()), "secretKey"
            )
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def userName(self):
        try:
            keyring = self.keyring()
            return keyring.get_password(self.userKeychainKey(self.user()), "userName")
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def userEmail(self):
        try:
            keyring = self.keyring()
            return keyring.get_password(self.userKeychainKey(self.user()), "userEmail")

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def createUserAccount(self, name, email, password1, password2):
        try:
            if self.online():

                if not name or not email or not password1 or not password2:
                    return False, "#(RequiredFieldEmpty)"

                if password1 != password2:
                    return False, "#(PasswordsDontMatch)"

                parameters = {
                    "name": name,
                    "email": email,
                    "password": password1,
                }
                if self.secretServerAuthKey:
                    parameters["SECRETKEY"] = self.secretServerAuthKey

                success, response, responseObject = self.performRequest(
                    self.mothership + "/createUserAccount", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

                # success
                return self.linkUser(response["anonymousUserID"], response["secretKey"])

            else:
                return (
                    False,
                    ["#(response.notOnline)", "#(response.notOnline.headline)"],
                )

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def deleteUserAccount(self, email, password):
        try:

            if self.online():

                # Required parameters
                if not email or not password:
                    return False, "#(RequiredFieldEmpty)"

                # Unlink user first
                if self.userEmail() == email:
                    success, message = self.performUnlinkUser()
                    if not success:
                        return False, message

                parameters = {
                    "email": email,
                    "password": password,
                }

                success, response, responseObject = self.performRequest(
                    self.mothership + "/deleteUserAccount", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] != "success":
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

                # success

                return True, None

            else:
                return (
                    False,
                    ["#(response.notOnline)", "#(response.notOnline.headline)"],
                )
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def resendEmailVerification(self):
        try:
            parameters = {
                "email": self.userEmail(),
            }

            success, response, responseObject = self.performRequest(
                self.mothership + "/resendEmailVerification", parameters
            )

            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            # success
            return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def logInUserAccount(self, email, password):
        try:
            if not email or not password:
                return False, "#(RequiredFieldEmpty)"

            parameters = {
                "email": email,
                "password": password,
            }

            success, response, responseObject = self.performRequest(
                self.mothership + "/logInUserAccount", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            # success
            return self.linkUser(response["anonymousUserID"], response["secretKey"])

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def linkUser(self, userID, secretKey):
        try:
            # Set secret key now, so it doesn't show up in preferences when offline
            keyring = self.keyring()
            keyring.set_password(self.userKeychainKey(userID), "secretKey", secretKey)
            assert self.secretKey(userID) == secretKey

            self.appendCommands("linkUser", userID)
            self.appendCommands("syncSubscriptions")
            self.appendCommands("downloadSubscriptions")

            return self.performCommands()
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performLinkUser(self, userID):
        try:

            parameters = {
                "anonymousAppID": self.anonymousAppID(),
                "anonymousUserID": userID,
                "secretKey": self.secretKey(userID),
            }

            parameters = self.addMachineIDToParameters(parameters)

            success, response, responseObject = self.performRequest(
                self.mothership + "/linkTypeWorldUserAccount", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            # Success
            self.set("typeworldUserAccount", userID)
            assert userID == self.user()

            # ZMQ
            topicID = "user-%s" % self.user()
            self.registerZMQCallback(topicID, self.zmqCallback)

            keyring = self.keyring()
            if "userEmail" in response:
                keyring.set_password(
                    self.userKeychainKey(userID), "userEmail", response["userEmail"]
                )
            if "userName" in response:
                keyring.set_password(
                    self.userKeychainKey(userID), "userName", response["userName"]
                )

            return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def linkedAppInstances(self):
        try:
            if not self.user():
                return False, "No user"

            parameters = {
                "anonymousAppID": self.anonymousAppID(),
                "anonymousUserID": self.user(),
                "secretKey": self.secretKey(),
            }

            success, response, responseObject = self.performRequest(
                self.mothership + "/userAppInstances", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            class AppInstance(object):
                pass

            # Success
            instances = []

            for serverInstance in response["appInstances"]:

                instance = AppInstance()

                for key in serverInstance:
                    setattr(instance, key, serverInstance[key])

                instances.append(instance)

            return True, instances
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def revokeAppInstance(self, anonymousAppID=None):
        try:
            if not self.user():
                return False, "No user"

            parameters = {
                "anonymousAppID": anonymousAppID or self.anonymousAppID(),
                "anonymousUserID": self.user(),
                "secretKey": self.secretKey(),
            }

            success, response, responseObject = self.performRequest(
                self.mothership + "/revokeAppInstance", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            return True, None
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def reactivateAppInstance(self, anonymousAppID=None):
        try:

            if not self.user():
                return False, "No user"

            parameters = {
                "anonymousAppID": anonymousAppID or self.anonymousAppID(),
                "anonymousUserID": self.user(),
                "secretKey": self.secretKey(),
            }

            success, response, responseObject = self.performRequest(
                self.mothership + "/reactivateAppInstance", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            if response["response"] != "success":
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            return True, None
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def unlinkUser(self):
        try:
            self.appendCommands("unlinkUser")
            return self.performCommands()
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def uninstallAllProtectedFonts(self, dryRun=False):
        try:
            # Uninstall all protected fonts
            for publisher in self.publishers():
                for subscription in publisher.subscriptions():

                    (
                        success,
                        installabeFontsCommand,
                    ) = subscription.protocol.installableFontsCommand()
                    assert success

                    fontIDs = []

                    for foundry in installabeFontsCommand.foundries:
                        for family in foundry.families:
                            for font in family.fonts:

                                # Dry run from central server: add all fonts to list
                                if dryRun and font.protected:
                                    fontIDs.append(
                                        font.uniqueID
                                    )  # nocoverage (This is executed only when the
                                    # central server uninstalls *all* fonts)

                                # Run from local client, add only actually installed
                                # fonts
                                elif (
                                    not dryRun
                                    and font.protected
                                    and subscription.installedFontVersion(font=font)
                                ):
                                    fontIDs.append(font.uniqueID)

                    if fontIDs:
                        success, message = subscription.removeFonts(
                            fontIDs, dryRun=dryRun, updateSubscription=False
                        )
                        if not success:
                            return False, message

            return True, None
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def performUnlinkUser(self):
        try:
            userID = self.user()

            success, response = self.uninstallAllProtectedFonts()
            if not success:
                return False, response

            parameters = {
                "anonymousAppID": self.anonymousAppID(),
                "anonymousUserID": userID,
                "secretKey": self.secretKey(),
            }

            success, response, responseObject = self.performRequest(
                self.mothership + "/unlinkTypeWorldUserAccount", parameters
            )
            if not success:
                return False, response

            response = json.loads(response.decode())

            continueFor = ["userUnknown"]
            if (
                response["response"] != "success"
                and not response["response"] in continueFor
            ):
                return (
                    False,
                    [
                        "#(response.%s)" % response["response"],
                        "#(response.%s.headline)" % response["response"],
                    ],
                )

            self.set("typeworldUserAccount", "")
            self.set("userAccountEmailIsVerified", "")
            self.remove("acceptedInvitations")
            self.remove("pendingInvitations")
            self.remove("sentInvitations")

            # ZMQ
            topicID = "user-%s" % userID
            self.unregisterZMQCallback(topicID)

            keyring = self.keyring()
            keyring.delete_password(self.userKeychainKey(userID), "secretKey")
            keyring.delete_password(self.userKeychainKey(userID), "userEmail")
            keyring.delete_password(self.userKeychainKey(userID), "userName")

            # Success
            return True, None

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def systemLocale(self):
        try:

            if not self._systemLocale:
                if MAC:
                    from AppKit import NSLocale

                    self._systemLocale = str(
                        NSLocale.preferredLanguages()[0].split("_")[0].split("-")[0]
                    )
                else:
                    import locale

                    self._systemLocale = locale.getdefaultlocale()[0].split("_")[0]

            return self._systemLocale
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def locale(self):
        try:

            """\
            Reads user locale from OS
            """

            if self.get("localizationType") == "systemLocale":
                _locale = [self.systemLocale()]
            elif self.get("localizationType") == "customLocale":
                _locale = [self.get("customLocaleChoice") or "en"]
            else:
                _locale = [self.systemLocale()]

            if "en" not in _locale:
                _locale.append("en")

            return _locale
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def expiringInstalledFonts(self):
        try:
            fonts = []
            for publisher in self.publishers():
                for subscription in publisher.subscriptions():
                    fonts.extend(subscription.expiringInstalledFonts())
            return fonts
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def amountOutdatedFonts(self):
        try:
            amount = 0
            for publisher in self.publishers():
                amount += publisher.amountOutdatedFonts()
            return amount
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def keyring(self):
        try:

            # Using keyring causes problems on all three MAC/WIN/LINUX
            # when used headlessly in a CI environment,
            # so we’re using the dummy for CI, which sucks because
            # then you can’t self-test thoroughly it during app build
            if (CI and not self.inCompiledApp) or GAE:
                keyring = dummyKeyRing
                return keyring

            import keyring  # nocoverage

            if MAC:  # nocoverage
                if self.inCompiledApp:
                    keyring.core.set_keyring(
                        keyring.core.load_keyring("keyring.backends.macOS.Keyring")
                    )  # nocoverage

            elif WIN:  # nocoverage
                keyring.core.set_keyring(
                    keyring.core.load_keyring(
                        "keyring.backends.Windows.WinVaultKeyring"
                    )
                )  # nocoverage

            elif LINUX:  # nocoverage
                keyring.core.set_keyring(
                    keyring.core.load_keyring("keyring.backends.kwallet.DBusKeyring")
                )  # nocoverage

            return keyring  # nocoverage

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def handleTraceback(self, file=None, sourceMethod=None, e=None):

        payload = f"""\
Version: {typeworld.api.VERSION}
{traceback.format_exc()}
"""

        # Remove path parts to make tracebacks identical (so they don't re-surface)

        def removePathPrefix(_payload, _snippet, _file):
            m = re.search(r'File "(.+?)"', _payload, re.MULTILINE)
            if m:
                _file = m.group(1)
                index = _file.find(_snippet)
                if index != -1:
                    clientPathPrefix = _file[:index]
                    return _payload.replace(clientPathPrefix, "")
                else:
                    return _payload
            else:
                return _payload  # nocoverage (this seems to never get executed,
                # because code always contains `File "..."` like it should.
                # Leaving this here just in case) TODO

        # Normalize file paths
        if WIN:
            payload = (
                removePathPrefix(payload, "TypeWorld.exe", __file__)
                .replace("\\", "/")
                .replace("TypeWorld.exe", "app.py")
            )
        payload = removePathPrefix(payload, "typeworld/client/", __file__).replace(
            "\\", "/"
        )
        payload = removePathPrefix(payload, "app.py", file).replace("\\", "/")

        # Create supplementary information
        supplementary = {
            "os": OSName(),
            "file": file or __file__,
            "preferences": self._preferences.dictionary(),
        }

        if sourceMethod:
            if hasattr(sourceMethod, "__self__") and sourceMethod.__self__:
                supplementary["sourceMethodSignature"] = (
                    str(sourceMethod.__self__.__class__.__name__)
                    + "."
                    + str(sourceMethod.__name__)
                    + str(inspect.signature(sourceMethod))
                )
            else:
                supplementary["sourceMethodSignature"] = str(  # nocoverage
                    sourceMethod.__name__  # nocoverage
                ) + str(  # nocoverage
                    inspect.signature(sourceMethod)  # nocoverage
                )  # nocoverage
                # (currently not testing for calling this method without
                # a sourceMethod parameter)

        supplementary["traceback"] = payload
        supplementary["stack"] = []
        supplementary["trace"] = []
        for s in inspect.stack():
            supplementary["stack"].append(
                {
                    "filename": str(s.filename),
                    "lineno": str(s.lineno),
                    "function": str(s.function),
                    "code_context": str(s.code_context[0].replace("\t", " ").rstrip())
                    if s.code_context
                    else None,
                }
            )
        for s in inspect.trace():
            supplementary["trace"].append(
                {
                    "filename": str(s.filename),
                    "lineno": str(s.lineno),
                    "function": str(s.function),
                    "code_context": str(s.code_context[0].replace("\t", " ").rstrip())
                    if s.code_context
                    else None,
                }
            )

        # replace faulty line of code (some Python versions include the faulty code
        # line in the traceback output, some not)
        if supplementary["trace"] and supplementary["trace"][0]["code_context"]:
            payload = payload.replace(supplementary["trace"][0]["code_context"], "")
            payload = payload.replace("\n \n", "\n")

        parameters = {
            "payload": payload,
            "supplementary": json.dumps(supplementary),
        }

        # Submit to central server
        # if self.online(self.mothership):

        def handleTracebackWorker(self):

            success, response, responseObject = self.performRequest(
                self.mothership + "/handleTraceback", parameters
            )
            if success:
                response = json.loads(response.decode())
                if response["response"] != "success":
                    self.log("handleTraceback() error on server, step 2: %s" % response)
            if not success:
                self.log("handleTraceback() error on server, step 1: %s" % response)

        handleTracebackThread = threading.Thread(
            target=handleTracebackWorker, args=(self,)
        )
        handleTracebackThread.start()

        # Log
        if sourceMethod:
            self.log(
                payload
                + "\nMethod signature:\n"
                + supplementary["sourceMethodSignature"]
            )
        else:
            self.log(payload)  # nocoverage  # nocoverage  # nocoverage
            # (currently not testing for calling this method without a sourceMethod
            # parameter)

        return False, payload

    def log(self, *arg):
        string = "Type.World: %s" % " ".join(map(str, arg))
        if MAC:
            nslog(string)
        else:
            logging.debug(string)

    def prepareUpdate(self):
        self._subscriptionsUpdated = []

    def allSubscriptionsUpdated(self):
        try:

            for publisher in self.publishers():
                for subscription in publisher.subscriptions():
                    if subscription.stillUpdating():
                        return False

            return True
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def deleteResources(self, urls):

        try:
            resources = self.get("resources") or {}

            for url in urls:
                for key in resources.keys():
                    if key.startswith(url):
                        del resources[key]
                        break

            self.set("resources", resources)

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def resourceByURL(self, url, binary=False, update=False):
        """Caches and returns content of a HTTP resource. If binary is set to True,
        content will be stored and return as a bas64-encoded string"""
        try:
            resources = self.get("resources") or {}

            key = f"{url},binary={binary}"

            # Load fresh
            if key not in resources or update:

                if self.testScenario:
                    url = addAttributeToURL(url, "testScenario=%s" % self.testScenario)

                success, response, responseObject = request(url, method="GET")
                if not success:
                    return False, response, responseObject.headers["content-type"]

                content = responseObject.content

                if binary:
                    content = base64.b64encode(content).decode()
                else:
                    content = content.decode()

                resources[key] = responseObject.headers["content-type"] + "," + content
                self.set("resources", resources)

                return True, content, responseObject.headers["content-type"]

            # Serve from cache
            else:

                response = resources[key]
                mimeType = response.split(",")[0]
                content = response[len(mimeType) + 1 :]

                return True, content, mimeType
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def anonymousAppID(self):
        try:
            anonymousAppID = self.get("anonymousAppID")

            if anonymousAppID is None or anonymousAppID == {}:
                import uuid

                anonymousAppID = str(uuid.uuid1())
                self.set("anonymousAppID", anonymousAppID)

            return anonymousAppID
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def endpointCommand(self, url):
        try:
            # Check for URL validity
            success, response = urlIsValid(url)
            if not success:
                return False, response

            # Get subscription
            success, protocol = getProtocol(url)
            protocol.client = self
            # Get Root Command
            return protocol.endpointCommand(testScenario=self.testScenario)
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def addSubscription(
        self,
        url,
        username=None,
        password=None,
        updateSubscriptionsOnServer=True,
        JSON=None,
    ):
        try:
            self._updatingProblem = None

            # Check for URL validity
            success, response = urlIsValid(url)
            if not success:
                return False, response, None, None

            # Get subscription
            success, message = getProtocol(url)
            if success:
                protocol = message
                protocol.client = self
            else:
                return False, message, None, None

            # Change secret key
            if protocol.unsecretURL() in self.unsecretSubscriptionURLs():

                # Initial endpointCommand
                success, message = self.endpointCommand(url)
                if success:
                    endpointCommand = message
                else:
                    return False, message, None, None

                protocol.setSecretKey(protocol.url.secretKey)
                publisher = self.publisher(endpointCommand.canonicalURL)
                subscription = publisher.subscription(protocol.unsecretURL(), protocol)

            else:

                # Initial Health Check
                success, response = protocol.aboutToAddSubscription(
                    anonymousAppID=self.anonymousAppID(),
                    anonymousTypeWorldUserID=self.user(),
                    accessToken=protocol.url.accessToken,
                    testScenario=self.testScenario,
                )
                if not success:
                    message = response
                    # self._updatingProblem = [
                    #     "#(response.loginRequired)",
                    #     "#(response.loginRequired.headline)",
                    # ]
                    return False, message, None, None

                # endpointCommand
                success, endpointCommand = protocol.endpointCommand(
                    testScenario=self.testScenario
                )
                assert success
                assert endpointCommand

                # Breaking API Version Check
                if "breakingAPIVersions" in self.get("downloadedSettings"):
                    breakingVersions = copy.copy(
                        self.get("downloadedSettings")["breakingAPIVersions"]
                    )
                    if self.testScenario == "simulateBreakingAPIVersion":
                        versionParts = breakingVersions[-1].split(".")
                        versionParts[0] = str(int(versionParts[0]) + 1)
                        breakingVersions.append(".".join(versionParts))

                    success, rootCommand = protocol.rootCommand(
                        testScenario=self.testScenario
                    )
                    assert success
                    assert rootCommand
                    incomingVersion = rootCommand.version

                    for breakingVersion in breakingVersions:
                        # Breaking version is higher than local API version
                        if (
                            semver.VersionInfo.parse(breakingVersion).compare(
                                typeworld.api.VERSION
                            )
                            == 1
                            # Incoming version is higher than breaking
                        ) and (
                            semver.VersionInfo.parse(incomingVersion).compare(
                                breakingVersion
                            )
                            == 1
                        ):
                            return (
                                False,
                                [
                                    "#(response.appUpdateRequired)",
                                    "#(response.appUpdateRequired.headline)",
                                ],
                                None,
                                None,
                            )

                # Commercial app check
                if (
                    self.commercial
                    and self.appID not in endpointCommand.allowedCommercialApps
                ):
                    return (
                        False,
                        [
                            "#(response.commercialAppNotAllowed)",
                            "#(response.commercialAppNotAllowed.headline)",
                        ],
                        None,
                        None,
                    )

                publisher = self.publisher(endpointCommand.canonicalURL)
                subscription = publisher.subscription(protocol.unsecretURL(), protocol)

                # Success
                subscription.save()
                publisher.save()
                subscription.stillAlive()
                self.manageMessageQueueConnection()

            if updateSubscriptionsOnServer:
                success, message = self.uploadSubscriptions()
                if not success:
                    return (
                        False,
                        message,
                        None,
                        None,
                    )  # 'Response from client.uploadSubscriptions(): %s' %

            protocol.subscriptionAdded()

            return True, None, publisher, subscription

        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def publisher(self, canonicalURL):
        try:
            if canonicalURL not in self._publishers:
                e = APIPublisher(self, canonicalURL)
                self._publishers[canonicalURL] = e

            if self.get("publishers") and canonicalURL in self.get("publishers"):
                self._publishers[canonicalURL].exists = True

            return self._publishers[canonicalURL]
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def publishers(self):
        try:
            if self.get("publishers"):
                publishers = []
                if self.get("publishers"):
                    for canonicalURL in self.get("publishers"):
                        publisher = self.publisher(canonicalURL)
                        if publisher.subscriptions():
                            publishers.append(publisher)
                return publishers
            else:
                return []
        except Exception as e:  # nocoverage
            return self.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )


class APIPublisher(object):
    """\
    Represents an API endpoint, identified and grouped by the canonical URL attribute
    of the API responses. This API endpoint class can then hold several repositories.
    """

    def __init__(self, parent, canonicalURL):
        self.parent = parent
        self.canonicalURL = canonicalURL
        self.exists = False
        self._subscriptions = {}

        self._updatingSubscriptions = []

    def folder(self):
        try:
            if WIN:
                return os.path.join(os.environ["WINDIR"], "Fonts")

            elif MAC:

                from os.path import expanduser

                home = expanduser("~")
                folder = os.path.join(home, "Library", "Fonts", "Type.World App")

                return folder

            else:
                import tempfile

                return tempfile.gettempdir()
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def stillUpdating(self):
        try:
            return len(self._updatingSubscriptions) > 0
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def updatingProblem(self):
        try:

            problems = []

            for subscription in self.subscriptions():
                problem = subscription.updatingProblem()
                if problem and problem not in problems:
                    problems.append(problem)

            if problems:
                return problems

        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def name(self, locale=["en"]):

        try:
            endpointCommand = self.subscriptions()[0].protocol.endpointCommand()[1]
            if endpointCommand:
                return endpointCommand.name.getTextAndLocale(locale=locale)
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def amountInstalledFonts(self):
        try:
            return len(self.installedFonts())
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def installedFonts(self):
        try:
            _list = []

            for subscription in self.subscriptions():
                for font in subscription.installedFonts():
                    if font not in _list:
                        _list.append(font)

            return _list
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def amountOutdatedFonts(self):
        try:
            return len(self.outdatedFonts())
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def outdatedFonts(self):
        try:
            _list = []

            for subscription in self.subscriptions():
                for font in subscription.outdatedFonts():
                    if font not in _list:
                        _list.append(font)

            return _list
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    # def currentSubscription(self):
    # 	if self.get('currentSubscription'):
    # 		subscription = self.subscription(self.get('currentSubscription'))
    # 		if subscription:
    # 			return subscription

    def get(self, key):
        try:
            preferences = self.parent.get("publisher(%s)" % self.canonicalURL) or {}
            if key in preferences:

                o = preferences[key]

                if "Array" in o.__class__.__name__:
                    o = list(o)
                elif "Dictionary" in o.__class__.__name__:
                    o = dict(o)

                return o
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def set(self, key, value):
        try:
            preferences = self.parent.get("publisher(%s)" % self.canonicalURL) or {}
            preferences[key] = value
            self.parent.set("publisher(%s)" % self.canonicalURL, preferences)
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    # def addGitHubSubscription(self, url, commits):

    # 	self.parent._subscriptions = {}

    # 	subscription = self.subscription(url)
    # 	subscription.set('commits', commits)
    # 	self.set('currentSubscription', url)
    # 	subscription.save()

    # 	return True, None

    def subscription(self, url, protocol=None):
        try:

            if url not in self._subscriptions:

                # Load from DB
                loadFromDB = False

                if not protocol:
                    success, message = getProtocol(url)
                    if success:
                        protocol = message
                        loadFromDB = True

                e = APISubscription(self, protocol)
                if loadFromDB:
                    protocol.loadFromDB()

                self._subscriptions[url] = e

            if self.get("subscriptions") and url in self.get("subscriptions"):
                self._subscriptions[url].exists = True

            return self._subscriptions[url]

        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def subscriptions(self):
        try:
            subscriptions = []
            if self.get("subscriptions"):
                for url in self.get("subscriptions"):
                    if urlIsValid(url)[0] is True:
                        subscriptions.append(self.subscription(url))
            return subscriptions
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def update(self):
        try:

            self.parent.prepareUpdate()

            changes = False

            if self.parent.online():

                for subscription in self.subscriptions():
                    success, message, change = subscription.update()
                    if change:
                        changes = True
                    if not success:
                        return success, message, changes

                return True, None, changes

            else:
                return (
                    False,
                    ["#(response.notOnline)", "#(response.notOnline.headline)"],
                    False,
                )
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def save(self):
        try:
            publishers = self.parent.get("publishers") or []
            if self.canonicalURL not in publishers:
                publishers.append(self.canonicalURL)
            self.parent.set("publishers", publishers)
        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def resourceByURL(self, url, binary=False, update=False):
        """Caches and returns content of a HTTP resource. If binary is set to True,
        content will be stored and return as a bas64-encoded string"""

        try:
            success, response, mimeType = self.parent.resourceByURL(url, binary, update)

            # Save resource
            if success is True:
                resourcesList = self.get("resources") or []
                if url not in resourcesList:
                    resourcesList.append(url)
                    self.set("resources", resourcesList)

            return success, response, mimeType

        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def delete(self):
        try:
            for subscription in self.subscriptions():
                success, message = subscription.delete(
                    calledFromParent=True, updateSubscriptionsOnServer=False
                )
                if not success:
                    return False, message

            # Resources
            self.parent.deleteResources(self.get("resources") or [])

            self.parent.remove("publisher(%s)" % self.canonicalURL)
            publishers = self.parent.get("publishers")
            publishers.remove(self.canonicalURL)
            self.parent.set("publishers", publishers)
            # self.parent.set('currentPublisher', '')

            # Sync to server
            self.parent.uploadSubscriptions()

            self.parent.delegate._publisherHasBeenDeleted(self)
            self.parent.manageMessageQueueConnection()

            self.parent._publishers = {}

            return True, None

        except Exception as e:  # nocoverage
            self.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )


class APISubscription(object):
    """\
    Represents a subscription, identified and grouped by the canonical URL attribute of
    the API responses.
    """

    def __init__(self, parent, protocol):
        try:
            self.parent = parent
            self.exists = False
            self.secretKey = None
            self.protocol = protocol
            self.protocol.subscription = self
            self.protocol.client = self.parent.parent
            self.url = self.protocol.unsecretURL()

            self.stillAliveTouched = None
            self._updatingProblem = None

            # ZMQ
            if self.parent.parent._isSetOnline and self.parent.parent.zmqSubscriptions:
                self.parent.parent.zmqSetup()
                self.parent.parent.registerZMQCallback(
                    self.zmqTopic(), self.zmqCallback
                )

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def zmqTopic(self):
        return "subscription-%s" % urllib.parse.quote_plus(
            self.protocol.shortUnsecretURL()
        )

    def __repr__(self):
        return f'<APISubscription url="{self.url}">'

    def uniqueID(self):
        try:
            uniqueID = self.get("uniqueID")

            if uniqueID is None or uniqueID == {}:
                # import uuid

                uniqueID = Garbage(10)
                self.set("uniqueID", uniqueID)

            return uniqueID
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def zmqCallback(self, message):
        try:
            if message:
                data = json.loads(message)
                if (
                    data["command"] == "pullUpdates"
                    and "sourceAnonymousAppID" not in data
                    or (
                        "sourceAnonymousAppID" in data
                        and data["sourceAnonymousAppID"]
                        != self.parent.parent.anonymousAppID()
                    )
                ):

                    delegate = self.parent.parent.delegate
                    delegate._subscriptionUpdateNotificationHasBeenReceived(self)

                    success, message, changes = self.update()
                    if success:
                        if "serverTimestamp" in data and data["serverTimestamp"]:
                            self.set("serverTimestamp", data["serverTimestamp"])

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    # TODO: Temporarily suspended because the central API updateSubscription requires
    # an APIKey parameter, so is intended only for publishers atm.
    # Here, this should be called after a protected font has been installed,
    # as it should update the used seats for that font

    # def announceChange(self):
    # 	try:

    # 		if not self.parent.parent.user(): return False, 'No user'

    # 		self.set('lastServerSync', int(time.time()))

    # 		parameters = {
    # 			'command': 'updateSubscription',
    # 			'anonymousAppID': self.parent.parent.anonymousAppID(),
    # 			'anonymousUserID': self.parent.parent.user(),
    # 			'subscriptionURL': self.protocol.url.secretURL(),
    # 			'secretKey': self.parent.parent.secretKey(),
    # 		}

    # 		success, response, responseObject =
    # self.parent.parent.performRequest(self.parent.parent.
    # mothership, parameters)
    # 		if not success:
    # 			return False, response

    # 		response = json.loads(response.decode())

    # 		if response['response'] != 'success':
    # 			return False, ['#(response.%s)' % response['response'], '#(response.%s.
    # headline)' % response['response']]

    # 		# Success
    # 		return True, None

    # 	except Exception as e: self.parent.parent.handleTraceback(sourceMethod =
    # getattr(self, sys._getframe().f_code.co_name), e = e)

    def hasProtectedFonts(self):
        try:
            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    for font in family.fonts:
                        if font.protected:
                            return True

            return False
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def stillAlive(self):

        try:

            def stillAliveWorker(self):

                # Register endpoint

                parameters = {
                    "url": "typeworld://%s+%s"
                    % (
                        self.protocol.url.protocol,
                        self.parent.canonicalURL.replace("://", "//"),
                    ),
                }

                success, response, responseObject = self.parent.parent.performRequest(
                    self.parent.parent.mothership + "/registerAPIEndpoint", parameters
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

            # Touch only once
            if not self.parent.parent.user():
                if not self.stillAliveTouched:

                    stillAliveThread = threading.Thread(
                        target=stillAliveWorker, args=(self,)
                    )
                    stillAliveThread.start()

                    self.stillAliveTouched = time.time()
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def inviteUser(self, targetEmail):
        print("inviteUser()")
        try:

            if self.parent.parent.online():

                if not self.parent.parent.userEmail():
                    return False, "No source user linked."

                parameters = {
                    "targetUserEmail": targetEmail,
                    "sourceUserEmail": self.parent.parent.userEmail(),
                    "subscriptionURL": self.protocol.secretURL(),
                }

                success, response, responseObject = self.parent.parent.performRequest(
                    self.parent.parent.mothership + "/inviteUserToSubscription",
                    parameters,
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())
                print(response)

                if response["response"] == "success":
                    return True, None
                else:
                    return (
                        False,
                        [
                            "#(response.%s)" % response["response"],
                            "#(response.%s.headline)" % response["response"],
                        ],
                    )

            else:
                return (
                    False,
                    ["#(response.notOnline)", "#(response.notOnline.headline)"],
                )
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def revokeUser(self, targetEmail):
        try:

            if self.parent.parent.online():

                parameters = {
                    "targetUserEmail": targetEmail,
                    "sourceUserEmail": self.parent.parent.userEmail(),
                    "subscriptionURL": self.protocol.secretURL(),
                }

                success, response, responseObject = self.parent.parent.performRequest(
                    self.parent.parent.mothership + "/revokeSubscriptionInvitation",
                    parameters,
                )
                if not success:
                    return False, response

                response = json.loads(response.decode())

                if response["response"] == "success":
                    return True, None
                else:
                    return False, response["response"]

            else:
                return (
                    False,
                    ["#(response.notOnline)", "#(response.notOnline.headline)"],
                )
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def invitationAccepted(self):
        try:

            if self.parent.parent.user():
                acceptedInvitations = self.parent.parent.acceptedInvitations()
                if acceptedInvitations:
                    for invitation in acceptedInvitations:
                        if self.protocol.unsecretURL() == invitation.url:
                            return True

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def stillUpdating(self):
        try:
            return self.url in self.parent._updatingSubscriptions
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def name(self, locale=["en"]):
        try:

            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            return installabeFontsCommand.name.getText(locale) or "#(Unnamed)"
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def resourceByURL(self, url, binary=False, update=False):
        """Caches and returns content of a HTTP resource. If binary is set to True,
        content will be stored and return as a bas64-encoded string"""
        try:
            success, response, mimeType = self.parent.parent.resourceByURL(
                url, binary, update
            )

            # Save resource
            if success is True:
                resourcesList = self.get("resources") or []
                if url not in resourcesList:
                    resourcesList.append(url)
                    self.set("resources", resourcesList)

            return success, response, mimeType

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def familyByID(self, ID):
        try:
            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    if family.uniqueID == ID:
                        return family
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def fontByID(self, ID):
        try:
            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    for font in family.fonts:
                        if font.uniqueID == ID:
                            return font
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def amountInstalledFonts(self):
        try:
            return len(self.installedFonts())
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def installedFonts(self):
        try:
            _list = []
            # Get font

            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    for font in family.fonts:
                        if self.installedFontVersion(font=font):
                            if font not in _list:
                                _list.append(font)
            return _list
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def expiringInstalledFonts(self):
        try:
            fonts = []
            # Get font

            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    for font in family.fonts:
                        if self.installedFontVersion(font=font) and font.expiry:
                            if font not in fonts:
                                fonts.append(font)
            return fonts
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def amountOutdatedFonts(self):
        try:
            return len(self.outdatedFonts())
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def outdatedFonts(self):
        try:
            _list = []

            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            # Get font
            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    for font in family.fonts:
                        installedFontVersion = self.installedFontVersion(font=font)
                        if (
                            installedFontVersion
                            and installedFontVersion != font.getVersions()[-1].number
                        ):
                            if font not in _list:
                                _list.append(font.uniqueID)
            return _list
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def installedFontVersion(self, fontID=None, font=None):
        try:

            folder = self.parent.folder()

            if fontID and not font:
                font = self.fontByID(fontID)

            for version in font.getVersions():
                path = os.path.join(
                    folder, self.uniqueID() + "-" + font.filename(version.number)
                )
                if os.path.exists(path):
                    return version.number

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    # def fontIsOutdated(self, fontID):

    # 	success, installabeFontsCommand = self.protocol.installableFontsCommand()

    # 	for foundry in installabeFontsCommand.foundries:
    # 		for family in foundry.families:
    # 			for font in family.fonts:
    # 				if font.uniqueID == fontID:

    # 					installedVersion = self.installedFontVersion(fontID)
    # 					return installedVersion and installedVersion != font.getVersions()[-1].number

    def removeFonts(self, fonts, dryRun=False, updateSubscription=True):
        try:
            success, installableFontsCommand = self.protocol.installableFontsCommand()

            uninstallTheseProtectedFontIDs = []
            uninstallTheseUnprotectedFontIDs = []

            folder = self.parent.folder()

            fontIDs = []

            for fontID in fonts:

                fontIDs.append(fontID)

                path = None
                font = self.fontByID(fontID)
                installedFontVersion = self.installedFontVersion(font=font)
                if installedFontVersion:
                    path = os.path.join(
                        folder,
                        self.uniqueID() + "-" + font.filename(installedFontVersion),
                    )

                if not path and not dryRun:
                    return False, "Font path couldn’t be determined (preflight)"

                if font.protected:

                    self.parent.parent.delegate._fontWillUninstall(font)

                    # Test for permissions here
                    if not dryRun:
                        try:
                            if (
                                self.parent.parent.testScenario
                                == "simulatePermissionError"
                            ):
                                raise PermissionError
                            else:
                                if not os.path.exists(os.path.dirname(path)):
                                    os.makedirs(os.path.dirname(path))
                                f = open(path + ".test", "w")
                                f.write("test")
                                f.close()
                                os.remove(path + ".test")
                        except PermissionError:
                            self.parent.parent.delegate._fontHasInstalled(
                                False,
                                "Insufficient permission to uninstall font.",
                                font,
                            )
                            return False, "Insufficient permission to uninstall font."

                        assert os.path.exists(path + ".test") is False

                    uninstallTheseProtectedFontIDs.append(fontID)

                else:
                    uninstallTheseUnprotectedFontIDs.append(fontID)

            assert self.parent.parent == self.protocol.client
            assert self.parent.parent.testScenario == self.protocol.client.testScenario

            # Server access
            # Protected fonts
            if uninstallTheseProtectedFontIDs:

                success, payload = self.protocol.removeFonts(
                    uninstallTheseProtectedFontIDs,
                    updateSubscription=updateSubscription,
                )

                font = None
                if success:

                    # # Security check
                    # if set([x.uniqueID for x in payload.assets]) - set(fontIDs) or
                    # set(fontIDs) - set([x.uniqueID for x in payload.assets]):
                    # 	return False, 'Incoming fonts’ uniqueIDs mismatch with requested
                    #  font IDs.'

                    if len(payload.assets) == 0:
                        return (
                            False,
                            (
                                "No fonts to uninstall in .assets, expected "
                                f"{len(uninstallTheseProtectedFontIDs)} assets"
                            ),
                        )

                    # Process fonts
                    for incomingFont in payload.assets:

                        if incomingFont.uniqueID in fontIDs:

                            proceed = ["unknownInstallation", "unknownFont"]  #

                            if incomingFont.response in proceed:
                                pass

                            # Predefined response messages
                            elif (
                                incomingFont.response != "error"
                                and incomingFont.response != "success"
                            ):
                                return (
                                    False,
                                    [
                                        "#(response.%s)" % incomingFont.response,
                                        "#(response.%s.headline)"
                                        % incomingFont.response,
                                    ],
                                )

                            elif incomingFont.response == "error":
                                return False, incomingFont.errorMessage

                            if incomingFont.response == "success":

                                path = None
                                font = self.fontByID(incomingFont.uniqueID)
                                installedFontVersion = self.installedFontVersion(
                                    font=font
                                )
                                if installedFontVersion:
                                    path = os.path.join(
                                        folder,
                                        self.uniqueID()
                                        + "-"
                                        + font.filename(installedFontVersion),
                                    )

                                if self.parent.parent.testScenario == "simulateNoPath":
                                    path = None

                                if not path and not dryRun:
                                    return (
                                        False,
                                        (
                                            "Font path couldn’t be determined "
                                            "(deleting unprotected fonts)"
                                        ),
                                    )

                                if not dryRun:
                                    os.remove(path)

                                self.parent.parent.delegate._fontHasUninstalled(
                                    True, None, font
                                )

                else:
                    self.parent.parent.delegate._fontHasUninstalled(
                        False, payload, font
                    )
                    return False, payload

            # Unprotected fonts
            if uninstallTheseUnprotectedFontIDs:

                for fontID in uninstallTheseUnprotectedFontIDs:

                    path = None
                    font = self.fontByID(fontID)
                    installedFontVersion = self.installedFontVersion(font=font)
                    if installedFontVersion:
                        path = os.path.join(
                            folder,
                            self.uniqueID() + "-" + font.filename(installedFontVersion),
                        )

                    if self.parent.parent.testScenario == "simulateNoPath":
                        path = None

                    if not path and not dryRun:
                        return (
                            False,
                            (
                                "Font path couldn’t be determined (deleting "
                                "unprotected fonts)"
                            ),
                        )

                    if not dryRun:
                        os.remove(path)

                    self.parent.parent.delegate._fontHasUninstalled(True, None, font)

            return True, None

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def installFonts(self, fonts):
        try:

            # Terms of Service
            if self.get("acceptedTermsOfService") is not True:
                return (
                    False,
                    [
                        "#(response.termsOfServiceNotAccepted)",
                        "#(response.termsOfServiceNotAccepted.headline)",
                    ],
                )

            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            installTheseFontIDs = []
            protectedFonts = False
            versionByFont = {}

            folder = self.parent.folder()

            fontIDs = []

            for fontID, version in fonts:

                fontIDs.append(fontID)
                versionByFont[fontID] = version

                path = None
                font = self.fontByID(fontID)
                path = os.path.join(
                    folder, self.uniqueID() + "-" + font.filename(version)
                )
                if font.protected or font.expiry or font.expiryDuration:
                    protectedFonts = True

                assert path
                assert font

                self.parent.parent.delegate._fontWillInstall(font)

                # Test for permissions here
                try:
                    if self.parent.parent.testScenario == "simulatePermissionError":
                        raise PermissionError
                    else:
                        if not os.path.exists(os.path.dirname(path)):
                            os.makedirs(os.path.dirname(path))
                        f = open(path + ".test", "w")
                        f.write("test")
                        f.close()
                        os.remove(path + ".test")
                except PermissionError:
                    self.parent.parent.delegate._fontHasInstalled(
                        False, "Insufficient permission to install font.", font
                    )
                    return False, "Insufficient permission to install font."

                assert os.path.exists(path + ".test") is False

                installTheseFontIDs.append(fontID)

            # Server access
            success, payload = self.protocol.installFonts(
                fonts, updateSubscription=protectedFonts
            )

            font = None
            if success:

                # Check for empty assets
                if len(payload.assets) == 0:
                    return (
                        False,
                        (
                            "No fonts to install in .assets, expected "
                            f"{len(installTheseFontIDs)} assets"
                        ),
                    )

                # Check if all requested fonts and fontVersions
                # are present in the assets
                for fontID, version in fonts:
                    if not [fontID, version] in [
                        [x.uniqueID, x.version] for x in payload.assets
                    ]:
                        return (
                            False,
                            (
                                f"Font {fontID} with version {version} "
                                "not found in assets"
                            ),
                        )

                # Process fonts
                for incomingFont in payload.assets:

                    if incomingFont.uniqueID in fontIDs:

                        if incomingFont.response == "error":
                            return False, incomingFont.errorMessage

                        # Predefined response messages
                        elif (
                            incomingFont.response != "error"
                            and incomingFont.response != "success"
                        ):
                            return (
                                False,
                                [
                                    "#(response.%s)" % incomingFont.response,
                                    "#(response.%s.headline)" % incomingFont.response,
                                ],
                            )

                        if incomingFont.response == "success":

                            path = None
                            font = self.fontByID(incomingFont.uniqueID)
                            path = os.path.join(
                                folder,
                                self.uniqueID()
                                + "-"
                                + font.filename(versionByFont[incomingFont.uniqueID]),
                            )
                            assert path

                            if not os.path.exists(os.path.dirname(path)):
                                os.makedirs(os.path.dirname(path))

                            if incomingFont.data and incomingFont.encoding:

                                f = open(path, "wb")
                                f.write(base64.b64decode(incomingFont.data))
                                f.close()

                            elif incomingFont.dataURL:

                                (
                                    success,
                                    response,
                                    responseObject,
                                ) = self.parent.parent.performRequest(
                                    incomingFont.dataURL, method="GET"
                                )

                                if not success:
                                    return False, response

                                else:
                                    f = open(path, "wb")
                                    f.write(response)
                                    f.close()

                            self.parent.parent.delegate._fontHasInstalled(
                                True, None, font
                            )

                # Ping
                self.stillAlive()

                return True, None

            else:
                self.parent.parent.delegate._fontHasInstalled(False, payload, font)
                return False, payload

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def update(self):
        try:
            self.parent._updatingSubscriptions.append(self.url)

            if self.parent.parent.online(self.protocol.url.restDomain.split("/")[0]):

                self.parent.parent.delegate._subscriptionWillUpdate(self)

                self.stillAlive()

                success, message, changes = self.protocol.update()

                if self.url in self.parent._updatingSubscriptions:
                    self.parent._updatingSubscriptions.remove(self.url)
                self._updatingProblem = None
                self.parent.parent._subscriptionsUpdated.append(self.url)

                if not success:
                    self.parent.parent.delegate._subscriptionHasBeenUpdated(
                        self, success, message, changes
                    )
                    return success, message, changes

                if changes:
                    self.save()

                # Success
                self.parent.parent.delegate._subscriptionHasBeenUpdated(
                    self, True, None, changes
                )
                return True, None, changes

            else:
                self.parent._updatingSubscriptions.remove(self.url)
                self.parent.parent._subscriptionsUpdated.append(self.url)
                self._updatingProblem = [
                    "#(response.serverNotReachable)",
                    "#(response.serverNotReachable.headline)",
                ]

                self.parent.parent.delegate._subscriptionHasBeenUpdated(
                    self, False, self._updatingProblem, False
                )

                return False, self._updatingProblem, False

        except Exception as e:  # nocoverage
            success, message = self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )
            return False, message, False

    def updatingProblem(self):
        try:
            return self._updatingProblem
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def get(self, key):
        try:
            preferences = dict(
                self.parent.parent.get("subscription(%s)" % self.protocol.unsecretURL())
                or {}
            )
            if key in preferences:

                o = preferences[key]

                if "Array" in o.__class__.__name__:
                    o = list(o)
                elif "Dictionary" in o.__class__.__name__:
                    o = dict(o)

                return o

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def set(self, key, value):
        try:

            preferences = dict(
                self.parent.parent.get("subscription(%s)" % self.protocol.unsecretURL())
                or {}
            )
            preferences[key] = value
            self.parent.parent.set(
                "subscription(%s)" % self.protocol.unsecretURL(), preferences
            )
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def save(self):
        try:
            subscriptions = self.parent.get("subscriptions") or []
            if not self.protocol.unsecretURL() in subscriptions:
                subscriptions.append(self.protocol.unsecretURL())
            self.parent.set("subscriptions", subscriptions)

            self.protocol.save()
        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )

    def delete(self, calledFromParent=False, updateSubscriptionsOnServer=True):
        try:
            success, installabeFontsCommand = self.protocol.installableFontsCommand()

            # Delete all fonts
            for foundry in installabeFontsCommand.foundries:
                for family in foundry.families:
                    for font in family.fonts:
                        self.removeFonts([font.uniqueID])

            # Key
            try:
                self.protocol.deleteSecretKey()
            except Exception:
                pass

            # ZMQ
            self.parent.parent.unregisterZMQCallback(self.zmqTopic())

            # Resources
            self.parent.parent.deleteResources(self.get("resources") or [])

            self.parent.parent.remove("subscription(%s)" % self.protocol.unsecretURL())

            # Subscriptions
            subscriptions = self.parent.get("subscriptions") or []
            subscriptions.remove(self.protocol.unsecretURL())
            self.parent.set("subscriptions", subscriptions)
            self.parent._subscriptions = {}

            # # currentSubscription
            # if self.parent.get('currentSubscription') == self.protocol.unsecretURL():
            # 	if len(subscriptions) >= 1:
            # 		self.parent.set('currentSubscription', subscriptions[0])

            self.parent._subscriptions = {}

            if len(subscriptions) == 0 and calledFromParent is False:
                self.parent.delete()

            self.parent.parent.delegate._subscriptionHasBeenDeleted(self)
            self.parent.parent.manageMessageQueueConnection()

            if updateSubscriptionsOnServer:
                self.parent.parent.uploadSubscriptions()

            return True, None

        except Exception as e:  # nocoverage
            self.parent.parent.handleTraceback(  # nocoverage
                sourceMethod=getattr(self, sys._getframe().f_code.co_name), e=e
            )
