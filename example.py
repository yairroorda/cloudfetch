import logging
from pathlib import Path

from shapely.geometry import Polygon as ShapelyPolygon  # type: ignore

from cloudfetch import AHN5, AHN6, CanElevation, IGNLidarHD
from cloudfetch.base import AOIPolygon, ProviderChain

# make sure data directory exists
data_dir = Path("./data")
data_dir.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] | %(name)s | %(message)s")


def demo_AHN():
    # Declare AOIs
    aoi_ahn6 = None
    aoi_ahn5 = None
    aoi_user = None

    aoi_ahn6 = AOIPolygon(ShapelyPolygon([(233691, 581987), (233875, 582056), (233921, 581956), (233758, 581894), (233691, 581987)]), crs="EPSG:28992")
    aoi_ahn5 = AOIPolygon(ShapelyPolygon([(4.371344115804476, 52.00696011579659), (4.368973043035311, 52.005236359264856), (4.370453622411532, 52.00450985195055), (4.372813966344637, 52.00625344969275), (4.371344115804476, 52.00696011579659)]), crs="EPSG:4326")
    # aoi_user = AOIPolygon.get_from_user("Draw AOI for AHN demo")

    ahn6 = AHN6(data_dir="./data")
    ahn5 = AHN5(data_dir="./data")
    ahn_chain = ProviderChain(providers=[ahn6, ahn5])

    for aoi in [aoi_user, aoi_ahn6, aoi_ahn5]:
        if aoi is None:
            continue
        result_path = ahn_chain.fetch(aoi=aoi.polygon, aoi_crs=aoi.crs, output_path=f"./data/{aoi.crs}_{aoi.polygon.area}.copc.laz")

        if result_path:
            logger.info(f"✅ Success! Successfully downloaded and processed at: {result_path}")
        else:
            logger.error("❌ Failed to retrieve data from any source in the chain.")


def demo_sampling():
    aoi_rdnew = AOIPolygon.get_from_user("Draw AOI for sampling demo")
    provider = AHN6(data_dir="./data")
    for sampling_radius in [None, 0.5, 1.0, 2.0]:
        output_path = Path(f"./data/sampling_test_{sampling_radius}.copc.laz")
        result_path = provider.fetch(aoi=aoi_rdnew.polygon, aoi_crs=aoi_rdnew.crs, output_path=output_path, sampling_radius=sampling_radius)
        if result_path:
            logger.info(f"✅ Success with sampling_radius={sampling_radius}! Output at: {result_path}")
        else:
            logger.error(f"❌ Failed to fetch data with sampling_radius={sampling_radius}.")


def demo_lidar_hd():
    aoi_wgs84 = AOIPolygon(
        ShapelyPolygon([(2.335270987781712, 48.862575335381095), (2.333844052585789, 48.86009786319193), (2.3366013634530987, 48.85942024260344), (2.339294301304051, 48.85932848077683), (2.3401311505166973, 48.86090958411185), (2.337888823780247, 48.861876573590436), (2.335270987781712, 48.862575335381095)]),
        crs="EPSG:4326",
    )
    lidarhd = IGNLidarHD(data_dir="./data")
    result_path = lidarhd.fetch(aoi=aoi_wgs84.polygon, aoi_crs=aoi_wgs84.crs, output_path="./data/louvre.copc.laz")

    if result_path:
        logger.info(f"✅ Success! Data successfully downloaded and processed at: {result_path}")
    else:
        logger.error("❌ Failed to retrieve data from any source in the chain.")


def demo_can_elevation():
    Ottowa = AOIPolygon(ShapelyPolygon([(-75.69165642094845, 45.42001546795836), (-75.69047088456387, 45.42045600726897), (-75.6899719936871, 45.41996463627825), (-75.69121117425198, 45.419516562451804), (-75.69165642094845, 45.42001546795836)]), crs="EPSG:4326")
    Montreal = AOIPolygon(ShapelyPolygon([(-73.57846058661653, 45.50615745142015), (-73.57840694243623, 45.504631049738535), (-73.57556380088045, 45.50326251649175), (-73.57419050986482, 45.50448066309671), (-73.57726968581392, 45.50615745142015), (-73.57846058661653, 45.50615745142015)]), crs="EPSG:4326")
    Edmonton = AOIPolygon(
        ShapelyPolygon([(-113.49083358598278, 53.54444831054993), (-113.49069411111401, 53.54339959958662), (-113.48897213292645, 53.54342191285635), (-113.48920280290173, 53.54471606479758), (-113.48968560052441, 53.5461523624816), (-113.49084967923687, 53.546094989179636), (-113.49083358598278, 53.54444831054993)]),
        crs="EPSG:4326",
    )
    Vancouver_island = AOIPolygon(ShapelyPolygon([(-127.91557599838546, 50.94038223123576), (-127.91540433700851, 50.93521688611795), (-127.90295888717941, 50.935379156997385), (-127.90274431045822, 50.940814904257685), (-127.91557599838546, 50.94038223123576)]), crs="EPSG:4326")

    # aoi_wgs84 = AOIPolygon.get_from_user("Draw AOI for CanElevation demo")
    # print(aoi_wgs84)

    for aoi, name in zip([Ottowa, Montreal, Edmonton, Vancouver_island], ["Ottawa", "Montreal", "Edmonton", "Vancouver Island"]):
        logger.info(f"Fetching data for {name} with CRS {aoi.crs}")

        canelevation = CanElevation(data_dir="./data")
        result_path = canelevation.fetch(aoi=aoi.polygon, aoi_crs=aoi.crs, output_path=f"./data/{name}.copc.laz")

        if result_path:
            logger.info(f"✅ Success! Data successfully downloaded and processed at: {result_path}")
        else:
            logger.error("❌ Failed to retrieve data from any source in the chain.")


def main():

    demo_AHN()
    demo_lidar_hd()
    demo_can_elevation()
    demo_sampling()


if __name__ == "__main__":
    main()
