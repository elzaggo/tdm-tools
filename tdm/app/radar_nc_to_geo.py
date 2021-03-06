# Copyright 2018-2019 CRS4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from netCDF4 import Dataset
import datetime
import os

import cf_units
import gdal

from tdm.radar import utils

gdal.UseExceptions()
strftime = datetime.datetime.strftime


# https://www.awaresystems.be/imaging/tiff/tifftags/datetime.html
FMT = "%Y-%m-%d %H:%M:%S"

# http://cfconventions.org/standard-names.html
RAINFALL_RATE_NAME = "rainfall_rate"
X_NAME = "projection_x_coordinate"
Y_NAME = "projection_y_coordinate"
TIME_NAME = "time"


class MemRasterBuilder(object):

    def __init__(self, geo_tr, wkt):
        self.driver = gdal.GetDriverByName("MEM")
        self.geo_tr = geo_tr
        self.wkt = wkt

    def build(self, data):
        rows, cols = data.shape
        raster = self.driver.Create("", cols, rows, 1, gdal.GDT_Float32)
        band = raster.GetRasterBand(1)
        band.WriteArray(data.filled())
        band.SetNoDataValue(float(data.fill_value))
        band.FlushCache()  # useless?
        raster.SetGeoTransform(self.geo_tr)
        raster.SetProjection(self.wkt)
        return raster


def get_geo_transform(x, y):
    xu, yu = cf_units.Unit(x.units), cf_units.Unit(y.units)
    meters = cf_units.Unit("m")
    oX = xu.convert(x[0].data.item(), meters)
    oY = yu.convert(y[0].data.item(), meters)
    pxlW = xu.convert(x[1] - x[0], meters)
    pxlH = yu.convert(y[1] - y[0], meters)
    return oX, pxlW, 0, oY, 0, pxlH


def get_vars(dataset):
    by_std_name = {getattr(_, "standard_name", None): _
                   for _ in dataset.variables.values()}
    x = by_std_name[X_NAME]
    y = by_std_name[Y_NAME]
    t = by_std_name[TIME_NAME]
    rf_rate = by_std_name[RAINFALL_RATE_NAME]
    return x, y, t, rf_rate


def main(args):
    try:
        os.makedirs(args.out_dir)
    except FileExistsError:
        pass
    ds = Dataset(args.nc_path, "r")
    x, y, t, rf_rate = get_vars(ds)
    u = cf_units.Unit(t.units)
    dts = [u.num2date(_) for _ in t]
    t_srs = "EPSG:4326"
    geo_tr = get_geo_transform(x, y)
    try:
        grid_mapping = ds.variables[rf_rate.grid_mapping]
    except (AttributeError, KeyError):
        raise RuntimeError("rainfall rate: grid mapping not found")
    raster_builder = MemRasterBuilder(geo_tr, grid_mapping.crs_wkt)
    out_driver = gdal.GetDriverByName("GTiff")
    nt = len(dts)
    print("saving to %s" % args.out_dir)
    for i, (dt, data) in enumerate(zip(dts, rf_rate)):
        out_dt = strftime(dt, utils.FMT)
        print("  %s (%d/%d)" % (out_dt, i + 1, nt))
        raster = raster_builder.build(data)
        warped_raster = gdal.Warp("", raster, format="MEM", dstSRS=t_srs)
        warped_raster.SetMetadata({"TIFFTAG_DATETIME": strftime(dt, FMT)})
        out_path = os.path.join(args.out_dir, "%s.tif" % out_dt)
        out_driver.CreateCopy(out_path, warped_raster)


def add_parser(subparsers):
    parser = subparsers.add_parser("radar_nc_to_geo")
    parser.add_argument("nc_path", metavar="NETCDF_FILE")
    parser.add_argument("-o", "--out-dir", metavar="DIR", default=os.getcwd())
    parser.set_defaults(func=main)
