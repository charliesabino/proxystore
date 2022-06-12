"""Signaling server implementation for WebRTC peer connections."""
from __future__ import annotations

import argparse
import asyncio
import datetime
import logging.handlers
import os
import signal
import sys
from dataclasses import dataclass
from socket import gethostname
from typing import Sequence
from uuid import UUID
from uuid import uuid4

import websockets.client
import websockets.exceptions
from websockets.client import WebSocketClientProtocol
from websockets.server import WebSocketServerProtocol

from proxystore.p2p.exceptions import PeerRegistrationError
from proxystore.p2p.exceptions import PeerUnknownError
from proxystore.p2p.messages import BaseMessage
from proxystore.p2p.messages import PeerConnectionMessage
from proxystore.p2p.messages import PeerRegistrationRequest
from proxystore.p2p.messages import PeerRegistrationResponse
from proxystore.p2p.messages import ServerError
from proxystore.serialize import deserialize
from proxystore.serialize import SerializationError
from proxystore.serialize import serialize

logger = logging.getLogger(__name__)


@dataclass
class Client:
    """Representation of client connection."""

    name: str
    uuid: UUID
    websocket: WebSocketServerProtocol


class SignalingServer:
    """Signaling Server implementation.

    The Signaling Server acts as a public third-party that helps two peers
    (endpoints) establish a peer-to-peer connection during the WebRTC
    peer connection initiation process. The signaling server's responsibility
    is just to forward session descriptions between two peers, so the
    server can be relatively lightweight and typically only needs to transfer
    two messages to establish a peer connection, after which the peers no
    longer need the signaling server.

    To learn more about the WebRTC peer connection process, check out
    `<https://webrtc.org/getting-started/peer-connections>`_.

    The signaling server is built on websockets and designed to be
    served using :code:`websockets.serve`.

    .. code-block:: python

       import websockets
       from proxystore.p2p.server import SignalingServer

       signaling_server = SignalingServer()
       async with websockets.serve(
            signaling_server.handler, host='localhost', port=1234
       ) as websocket_server:
           ...
    """

    def __init__(self) -> None:
        """Init SignalingServer."""
        self._websocket_to_client: dict[WebSocketServerProtocol, Client] = {}
        self._uuid_to_client: dict[UUID, Client] = {}

    async def send(
        self,
        websocket: WebSocketServerProtocol,
        message: BaseMessage,
    ) -> None:
        """Send message on the socket.

        Args:
            websocket (WebSocketServerProtocol): websocket to send message on.
            message (BaseMesssage): message to serialize and send.
        """
        message_bytes = serialize(message)
        await websocket.send(message_bytes)

    async def register(
        self,
        websocket: WebSocketServerProtocol,
        request: PeerRegistrationRequest,
    ) -> None:
        """Register peer with Signaling Server.

        Args:
            websocket (WebSocketServerProtocol): websocket connection with
                client wanting to register.
            request (PeerRegistrationRequest): registration request message.
        """
        if request.uuid is None:
            # New client so generate uuid for them
            uuid_ = uuid4()
        else:
            uuid_ = request.uuid

        if websocket not in self._websocket_to_client:
            # Check if previous client reconnected on new socket so unregister
            # old socket. Warning: could be a client impersontating another
            if uuid_ in self._uuid_to_client:
                logger.info(
                    f'previously registered client {uuid_} attempting to '
                    'reregister so old registration will be removed',
                )
                await self.unregister(
                    self._uuid_to_client[uuid_].websocket,
                    False,
                )
            client = Client(
                name=request.name,
                uuid=uuid_,
                websocket=websocket,
            )
            self._websocket_to_client[websocket] = client
            self._uuid_to_client[client.uuid] = client
            logger.info(
                f'registered {client.uuid} ({client.name} at '
                f'{websocket.remote_address})',
            )
        else:
            client = self._websocket_to_client[websocket]
            logger.info(
                f'previously registered client {client.uuid} attempting to '
                'reregister so previous registration will be returned',
            )

        await self.send(
            websocket,
            PeerRegistrationResponse(uuid=client.uuid),
        )

    async def unregister(
        self,
        websocket: WebSocketServerProtocol,
        expected: bool,
    ) -> None:
        """Unregister the endpoint.

        Args:
            websocket (WebSocketServerProtocol): websocket connection that
                was closed.
            expected (bool): if the connection was closed intentionally or
                due to an error.
        """
        client = self._websocket_to_client.pop(websocket, None)
        if client is None:
            # Most likely websocket closed before registration was performed
            return
        reason = 'ok' if expected else 'unexpected'
        logger.info(
            f'unregistering client {client.uuid} ({client.name}) '
            f'for {reason} reason',
        )
        self._uuid_to_client.pop(client.uuid, None)
        await client.websocket.close(code=1000 if expected else 1001)

    async def connect(
        self,
        websocket: WebSocketServerProtocol,
        message: PeerConnectionMessage,
    ) -> None:
        """Pass peer connection messages between clients.

        Args:
            websocket (WebSocketServerProtocol): websocket connection with
                client that sent the peer connection message.
            message (PeerConnectionMessage): message to forward to peer client.
        """
        client = self._websocket_to_client[websocket]
        if message.peer_uuid not in self._uuid_to_client:
            logger.warning(
                f'client {client.uuid} ({client.name}) attempting to send '
                f'message to unknown peer {message.peer_uuid}',
            )
            await self.send(
                websocket,
                PeerConnectionMessage(
                    source_uuid=self._websocket_to_client[websocket].uuid,
                    source_name=self._websocket_to_client[websocket].name,
                    peer_uuid=message.peer_uuid,
                    error=PeerUnknownError(
                        f'peer {message.peer_uuid} is unknown',
                    ),
                ),
            )
            return

        peer_client = self._uuid_to_client[message.peer_uuid]
        logger.info(
            f'transmitting message from {client.uuid} ({client.name}) '
            f'to {message.peer_uuid}',
        )
        await self.send(peer_client.websocket, message)

    async def handler(
        self,
        websocket: WebSocketServerProtocol,
        uri: str,
    ) -> None:
        """Websocket server message handler.

        Args:
            websocket (WebSocketServerProtocol): websocket message was
                received on.
            uri (str): uri message was sent to.
        """
        logger.info('signaling server listening for incoming connections')
        while True:
            try:
                message = await websocket.recv()
                if isinstance(message, bytes):
                    message = deserialize(message)
                else:
                    raise AssertionError(
                        'Received non-bytes type on websocket.',
                    )
            except websockets.exceptions.ConnectionClosedOK:
                await self.unregister(websocket, expected=True)
                break
            except websockets.exceptions.ConnectionClosedError:
                await self.unregister(websocket, expected=False)
                break
            except SerializationError:
                logger.error(
                    'caught deserialization error on message received from '
                    f'{websocket.remote_address}... skipping message',
                )
                continue

            if isinstance(message, PeerRegistrationRequest):
                await self.register(websocket, message)
            elif isinstance(message, PeerConnectionMessage):
                if websocket in self._websocket_to_client:
                    await self.connect(websocket, message)
                else:
                    # If message is not a registration request but this client
                    # has not yet registered, let them know
                    logger.info(
                        'returning server error to message received from '
                        f'unregistered client {message.source_uuid} '
                        f'({message.source_name})',
                    )
                    await self.send(
                        websocket,
                        ServerError('client has not registered yet'),
                    )
            else:
                logger.error(
                    'returning server error to client at '
                    f'{websocket.remote_address} that sent unknown request '
                    f'type {type(message).__name__}',
                )
                await self.send(
                    websocket,
                    ServerError('unknown request type'),
                )


async def connect(
    address: str,
    uuid: UUID | None = None,
    name: str | None = None,
    timeout: int = 10,
) -> tuple[UUID, str, WebSocketClientProtocol]:
    """Establish client connection to a Signaling Server.

    Args:
        address (str): address of the Signaling Server.
        uuid (str, optional): optional uuid of client to use when registering
            with signaling server (default: None).
        name (str, optional): readable name of the client to use when
            registering with the signaling server. By default the
            hostname will be used (default: None).
        timeout (int): time to wait in seconds on server connections
            (default: 10).

    Returns:
        tuple of the UUID of this client returned by the signaling server,
        the name used to register the client, and the websocket connection to
        the signaling server.

    Raises:
        EndpointRegistrationError:
            if the connection to the signaling server is closed, does not reply
            to the registration request within the timeout, or replies with an
            error.
    """
    if name is None:
        name = gethostname()

    websockets_version = int(websockets.__version__.split('.')[0])

    if websockets_version >= 10:
        websocket = await websockets.client.connect(
            f'ws://{address}',
            open_timeout=timeout,
        )
    else:  # pragma: no cover
        websocket = await websockets.client.connect(f'ws://{address}')

    await websocket.send(
        serialize(PeerRegistrationRequest(uuid=uuid, name=name)),
    )
    try:
        message = await asyncio.wait_for(websocket.recv(), timeout)
        if isinstance(message, bytes):
            message = deserialize(message)
        else:
            raise AssertionError('Received non-bytes type on websocket.')
    except websockets.exceptions.ConnectionClosed:
        raise PeerRegistrationError(
            'Connection to signaling server closed before peer '
            'registration completed.',
        )
    except asyncio.TimeoutError:
        raise PeerRegistrationError(
            'Signaling server did not reply to registration within timeout.',
        )

    if isinstance(message, PeerRegistrationResponse):
        if message.error is not None:
            raise PeerRegistrationError(
                'Failed to register as peer with signaling server. '
                f'Got exception: {message.error}',
            )
        logger.info(
            f'established client connection to signaling server at {address} '
            f'with uuid={message.uuid} and name={name}',
        )
        return message.uuid, name, websocket
    else:
        raise PeerRegistrationError(
            'Signaling server replied with unknown message type: '
            f'{type(message).__name__}.',
        )


async def serve(host: str, port: int) -> None:
    """Run the signaling server.

    Initializes a :class:`SignalingServer <.SignalingServer>` and starts a
    websocket server listening on `host:port` for new connections and
    incoming messages.

    Args:
        host (str): host to listen on.
        port (int): port to listen on.
    """
    server = SignalingServer()

    # Set the stop condition when receiving SIGINT (ctrl-C) and SIGTERM.
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    # TODO: add logger=logger kwarg to serve() if websockets dependency
    # is pinned to 10.0 or later
    async with websockets.server.serve(server.handler, host, port):
        logger.info(f'serving signaling server on {host}:{port}')
        logger.info('use ctrl-C to stop')
        await stop

    logger.info('server closed')


def main(argv: Sequence[str] | None = None) -> int:
    """CLI for starting the signaling server.

    Usage:

    .. code-block:: console

       $ signaling-server {options}
       $ signaling-server --help
    """
    parser = argparse.ArgumentParser(
        'Websocket-based Signaling Server',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='host to listen on',
    )
    parser.add_argument(
        '--port',
        default=8765,
        type=int,
        help='port to listen on',
    )
    parser.add_argument(
        '--log-dir',
        default=None,
        help='write logs named server.log.{timestamp} to this dir',
    )
    parser.add_argument(
        '--log-level',
        choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'],
        default='INFO',
        help='logging level',
    )
    args = parser.parse_args(argv)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log_dir is not None:
        os.makedirs(args.log_dir, exist_ok=True)
        handlers.append(
            logging.handlers.TimedRotatingFileHandler(
                os.path.join(args.log_dir, 'server.log'),
                # Rotate logs Sunday at midnight
                when='W6',
                atTime=datetime.time(hour=0, minute=0, second=0),
            ),
        )

    logging.basicConfig(
        format=(
            '[%(asctime)s.%(msecs)03d] %(levelname)-5s (%(name)s) :: '
            '%(message)s'
        ),
        datefmt='%Y-%m-%d %H:%M:%S',
        level=args.log_level,
        handlers=handlers,
    )

    asyncio.run(serve(args.host, args.port))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
