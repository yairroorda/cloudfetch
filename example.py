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
    # aoi_rdnew = AOIPolygon(ShapelyPolygon([(233691, 581987), (233875, 582056), (233921, 581956), (233758, 581894), (233691, 581987)]), crs="EPSG:28992")
    aoi_rdnew = AOIPolygon.get_from_user("Draw AOI for AHN demo")
    ahn6 = AHN6(data_dir="./data")
    ahn5 = AHN5(data_dir="./data")
    ahn_chain = ProviderChain(providers=[ahn6, ahn5])
    result_path = ahn_chain.fetch(aoi=aoi_rdnew.polygon, aoi_crs=aoi_rdnew.crs, output_path="./data/groningen_plein.copc.laz")

    if result_path:
        logger.info(f"✅ Success! Data successfully downloaded and processed at: {result_path}")
    else:
        logger.error("❌ Failed to retrieve data from any source in the chain.")


def demo_resolution():
    aoi_rdnew = AOIPolygon.get_from_user("Draw AOI for resolution demo")
    provider = AHN6(data_dir="./data")
    for resolution in ["full", 0.5, 1.0, 2.0]:
        output_path = Path(f"./data/resolution_test_{resolution or 'full'}.copc.laz")
        result_path = provider.fetch(aoi=aoi_rdnew.polygon, aoi_crs=aoi_rdnew.crs, output_path=output_path, resolution=resolution)
        if result_path:
            logger.info(f"✅ Success with resolution={resolution}! Output at: {result_path}")
        else:
            logger.error(f"❌ Failed to fetch data with resolution={resolution}.")


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
    # Ottowa = Polygon([(-75.69165642094845, 45.42001546795836), (-75.69047088456387, 45.42045600726897), (-75.6899719936871, 45.41996463627825), (-75.69121117425198, 45.419516562451804), (-75.69165642094845, 45.42001546795836)])
    Montreal = AOIPolygon(ShapelyPolygon([(-73.57846058661653, 45.50615745142015), (-73.57840694243623, 45.504631049738535), (-73.57556380088045, 45.50326251649175), (-73.57419050986482, 45.50448066309671), (-73.57726968581392, 45.50615745142015), (-73.57846058661653, 45.50615745142015)]), crs="EPSG:4326")
    # Vancouver_island = Polygon([(-127.91557599838546, 50.94038223123576), (-127.91540433700851, 50.93521688611795), (-127.90295888717941, 50.935379156997385), (-127.90274431045822, 50.940814904257685), (-127.91557599838546, 50.94038223123576)])

    # aoi_wgs84 = AOIPolygon.get_from_user("Draw AOI for CanElevation demo")
    # print(aoi_wgs84)

    canelevation = CanElevation(data_dir="./data")
    result_path = canelevation.fetch(aoi=Montreal.polygon, aoi_crs=Montreal.crs, output_path="./data/Montreal.copc.laz")

    if result_path:
        logger.info(f"✅ Success! Data successfully downloaded and processed at: {result_path}")
    else:
        logger.error("❌ Failed to retrieve data from any source in the chain.")


def main():

    demo_AHN()
    demo_lidar_hd()
    demo_can_elevation()
    demo_resolution()


if __name__ == "__main__":
    main()
