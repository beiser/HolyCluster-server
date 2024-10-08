from environs import Env

env = Env()
env.read_env()

PSQL_USERNAME = env.str("PSQL_USERNAME")
PSQL_PASSWORD = env.str("PSQL_PASSWORD")

QRZ_USER = env.str("QRZ_USER")
QRZ_PASSOWRD = env.str("QRZ_PASSWORD")
QRZ_API_KEY = env.str("QRZ_API_KEY")

HOST = "localhost"
PORT = "5432"

# Connect to the default 'postgres' database
DATABASE = "holy_cluster"

GENERAL_DB_URL = f"postgresql+psycopg2://{PSQL_USERNAME}:{PSQL_PASSWORD}@{HOST}:{PORT}"
DB_URL = f"{GENERAL_DB_URL}/{DATABASE}"


# Parameters for the API
SSL_KEYFILE = env.str("SSL_KEYFILE", None)
SSL_CERTFILE = env.str("SSL_CERTFILE", None)
SSL_AVAILABLE = SSL_KEYFILE is not None and SSL_CERTFILE is not None

UI_DIR = env.str("UI_DIR")
