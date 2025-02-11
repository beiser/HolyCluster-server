from contextlib import asynccontextmanager
import asyncio
import datetime
import logging
import time
from typing import Optional

from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import fastapi
import uvicorn

from sqlmodel import Field, SQLModel, create_engine, Session, select
from sqlalchemy import desc

from . import propagation, settings


class DX(SQLModel, table=True):
    __tablename__ = 'holy_spots'

    id: Optional[int] = Field(default=None, primary_key=True)
    dx_callsign: str
    dx_locator: str
    dx_lat: str
    dx_lon: str
    dx_country: str
    dx_continent: str
    spotter_callsign: str
    spotter_lat: str
    spotter_lon: str
    spotter_continent: str
    frequency: str
    band: str
    mode: str
    date_time: datetime.datetime
    comment: str


class SpotsWithIssues(SQLModel, table=True):
    __tablename__ = "spots_with_issues"
    id: Optional[int] = Field(default=None, primary_key=True)
    time: datetime.time
    date: datetime.date
    band: str
    frequency: str
    spotter_callsign: str
    spotter_locator: str
    spotter_lat: str
    spotter_lon: str
    spotter_country: str
    dx_callsign: str
    dx_locator: str
    dx_lat: str
    dx_lon: str
    dx_country: str
    comment: str


class GeoCache(SQLModel, table=True):
    __tablename__ = "geo_cache"
    callsign: str = Field(primary_key=True)
    locator: str


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def propagation_data_collector(app):
    while True:
        sleep = 3600
        try:
            app.state.propagation = await propagation.collect_propagation_data()
            app.state.propagation["time"] = int(time.time())
            logger.info(f"Got propagation data: {app.state.propagation}")
        except Exception as e:
            sleep = 10
            logger.error(f"Failed to fetch spots: {str(e)}")
        await asyncio.sleep(sleep)


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    asyncio.get_running_loop().create_task(propagation_data_collector(app))
    yield


engine = create_engine(settings.DB_URL)
app = fastapi.FastAPI(lifespan=lifespan)

if settings.SSL_AVAILABLE:
    import ssl
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(settings.SSL_CERTFILE, keyfile=settings.SSL_KEYFILE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def cleanup_spot(spot):
    if spot.mode.upper() in ("SSB", "USB", "LSB"):
        mode = "SSB"
    else:
        mode = spot.mode.upper()

    return {
        "id": spot.id,
        "spotter_callsign": spot.spotter_callsign,
        "spotter_loc": [float(spot.spotter_lon), float(spot.spotter_lat)],
        "spotter_continent": spot.spotter_continent,
        "dx_callsign": spot.dx_callsign,
        "dx_loc": [float(spot.dx_lon), float(spot.dx_lat)],
        "dx_locator": spot.dx_locator,
        "dx_country": spot.dx_country,
        "dx_continent": spot.dx_continent,
        "freq": int(float(spot.frequency)),
        "band": int(float(spot.band)),
        "mode": mode,
        "time": int(spot.date_time.timestamp()),
        "comment": spot.comment,
    }


@app.get("/spots")
def spots(since: Optional[int] = None):
    with Session(engine) as session:
        query = select(DX)
        if since is not None:
            query = query.where(DX.date_time > datetime.datetime.fromtimestamp(since))
        query = query.order_by(desc(DX.date_time)).limit(500)
        spots = session.exec(query).all()
        spots = [
            cleanup_spot(spot)
            for spot in spots
        ]
        return spots


@app.get("/geocache/all")
def geocache_all():
    with Session(engine) as session:
        geodata = session.exec(select(GeoCache)).all()
        return [data.model_dump() for data in geodata]


@app.get("/geocache/{callsign}")
def geocache(callsign: str):
    with Session(engine) as session:
        query = select(GeoCache).where(GeoCache.callsign == callsign.upper())
        geodata = session.exec(query).one_or_none()
        if geodata is not None:
            return geodata.model_dump()
        else:
            return {}


@app.get("/spots_with_issues")
def spots_with_issues():
    with Session(engine) as session:
        spots = session.exec(select(SpotsWithIssues)).all()
        spots = [spot.model_dump() for spot in spots]
        return spots


@app.get("/propagation")
def propagation_data():
    return app.state.propagation


@app.websocket("/radio")
async def radio(websocket: fastapi.WebSocket):
    """Dummy websockets endpoint to indicate to the client that radio connection is not available."""
    await websocket.accept()
    await websocket.send_json({"status": "unavailable"})
    await websocket.close()


async def send_dx_spot(cluster_host, cluster_port, spotter_callsign, dx_callsign, frequency):
    pass

# Example usage:
# asyncio.run(send_dx_spot("dxcluster.example.com", 7300, "YOURCALL", "DXCALL", "14000.0"))

CLUSTER_HOST = "dxc.k0xm.net"
CLUSTER_PORT = 7300


class InvalidSpotter(Exception):
    def __str__(self):
        return "Invalid spotter"


class LoginFailed(Exception):
    def __init__(self, response):
        self.response = response

    def __str__(self):
        return f"Invalid repsonse: {self.response}"


class CommandError(Exception):
    def __init__(self, command):
        self.command = command

    def __str__(self):
        return f"Invalid command: {self.command}"


@app.websocket("/submit_spot")
async def submit_spot(websocket: fastapi.WebSocket):
    """Dummy websockets endpoint to indicate to the client that radio connection is not available."""
    await websocket.accept()
    data = await websocket.receive_json()

    response = ""
    try:
        if data["spotter_callsign"] == "":
            raise InvalidSpotter()

        reader, writer = await asyncio.open_connection(CLUSTER_HOST, CLUSTER_PORT)
        writer.write(f"{data['spotter_callsign']}\n".encode())
        response = (await reader.read(1024)).decode()
        if "is not a valid callsign" in response:
            raise InvalidSpotter()
        elif "Hello" not in response:
            raise LoginFailed()

        comment = ""
        spot_command = f"DX {float(data['freq'])} {data['dx_callsign']} {comment}\n"
        writer.write(spot_command.encode())

        response = (await reader.read(1024)).decode()
        if "command error" in response:
            raise CommandError(spot_command)

        writer.close()
        await writer.wait_closed()

        await websocket.send_json({"result": "success", "output": response})
        logger.info(f"Spot submitted sucessfully: {data}")
    except Exception as e:
        logger.exception(f"Failed to submit spot: {data}")
        await websocket.send_json({
            "result": "failure",
            "type": e.__class__.__name__,
            "received_data": data,
            "error_data": str(e),
        })

    await websocket.close()


app.mount("/", StaticFiles(directory=settings.UI_DIR, html=True), name="static")


if __name__ == "__main__":
    if settings.SSL_AVAILABLE:
        port = 443
        ssl_kwargs = {
            "ssl_keyfile": settings.SSL_KEYFILE,
            "ssl_certfile": settings.SSL_CERTFILE
        }
    else:
        port = 80
        ssl_kwargs = {}

    uvicorn.run(app, host="0.0.0.0", port=port, **ssl_kwargs)
