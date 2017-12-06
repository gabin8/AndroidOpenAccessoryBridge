#!/usr/local/bin/python3
# coding=utf-8

# Copyright 2015 Christopher Blay <chris.b.blay@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function, unicode_literals

import array
import sys
import time
import usb


NEXUS4_USB_IDS = (0x18d1, 0x4ee2, 0x2d01)
_B = 'B' if sys.version_info.major == 3 else b'B'


class AndroidOpenAccessoryBridge:

    def __init__(self,
                 vendor_id, unconfigured_product_id, configured_product_id,
                 manufacturer, model, description, version, uri, serial):
        self._vendor_id = int(vendor_id)
        self._unconfigured_product_id = int(unconfigured_product_id)
        self._configured_product_id = int(configured_product_id)
        self._device = self._configureAndOpenDevice(
            str(manufacturer),
            str(model),
            str(description),
            str(version),
            str(uri),
            str(serial))
        self._endpoint_out, self._endpoint_in = self._detectEndpoints()

    def __enter__(self):
        return self  # All 'enter' work is done in __init__().

    def __exit__(self, type, value, traceback):
        self.close()

    def _detectDevice(self, attempts_left=5):
        unconfigured_device = usb.core.find(
            idVendor=self._vendor_id, idProduct=self._unconfigured_product_id)
        configured_device = usb.core.find(
            idVendor=self._vendor_id, idProduct=self._configured_product_id)
        if configured_device:
            return configured_device, True
        elif unconfigured_device:
            return unconfigured_device, False
        elif attempts_left:
            time.sleep(1)
            return self._detectDevice(attempts_left - 1)
        else:
            raise usb.core.USBError('Device not connected')

    def _configureAndOpenDevice(
            self, manufacturer, model, description, version, uri, serial):
        device, is_configured = self._detectDevice()
        if not is_configured:
            # Validate version code.
            buf = device.ctrl_transfer(0xc0, 51, data_or_wLength=2)
            assert(len(buf) == 2 and (buf[0] | buf[1] << 8) == 2)
            # Send accessory information.
            for i, data in enumerate(
                    (manufacturer, model, description, version, uri, serial)):
                assert(device.ctrl_transfer(
                       0x40, 52, wIndex=i, data_or_wLength=data) == len(data))
            # Put device into accessory mode.
            assert(device.ctrl_transfer(0x40, 53) == 0)
            usb.util.dispose_resources(device)
        else:
            # This brings your companion app back to foreground.
            device.reset()
            time.sleep(1)

        # Wait for configured device to show up
        attempts_left = 5
        while attempts_left:
            device, is_configured = self._detectDevice()
            if is_configured:
                return device
            time.sleep(1)
            attempts_left -= 1
        raise usb.core.USBError('Device not configured')

    def _detectEndpoints(self):
        assert(self._device)
        configuration = self._device.get_active_configuration()
        interface = configuration[(0, 0)]

        def first_out_endpoint(endpoint):
            return (usb.util.endpoint_direction(endpoint.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT)

        def first_in_endpoint(endpoint):
            return (usb.util.endpoint_direction(endpoint.bEndpointAddress)
                    == usb.util.ENDPOINT_IN)

        endpoint_out = usb.util.find_descriptor(
            interface, custom_match=first_out_endpoint)
        endpoint_in = usb.util.find_descriptor(
            interface, custom_match=first_in_endpoint)
        assert(endpoint_out and endpoint_in)
        return endpoint_out, endpoint_in

    def write(self, data, timeout=None):
        assert(self._device and self._endpoint_out and data)
        size = len(data)
        size_bytes = array.array(_B, [
            (size & 0x0000ff00) >> 8,
            (size & 0x000000ff)])
        data_bytes = array.array(_B, data)
        while True:
            try:
                bytes_wrote = self._endpoint_out.write(size_bytes,
                                                       timeout=timeout)
            except usb.core.USBError as e:
                if e.errno == 110:  # Operation timed out
                    continue
                else:
                    raise e
            else:
                assert(bytes_wrote == 2)
                break
        assert(self._endpoint_out.write(data_bytes, timeout=timeout) == size)

    def read(self, timeout=None):
        assert(self._device and self._endpoint_in)
        try:
            size_bytes = self._endpoint_in.read(2, timeout=timeout)
            size = (size_bytes[0] << 8) | size_bytes[1]
            return self._endpoint_in.read(size, timeout=timeout).tostring()
        except usb.core.USBError as e:
            if e.errno == 110:  # Operation timed out.
                return None
            else:
                raise e

    def close(self):
        assert(self._device and self._endpoint_out)
        self._endpoint_out.write(array.array(_B, [0, 0]))
        usb.util.dispose_resources(self._device)
        self._device = None
        self._endpoint_out = None
        self._endpoint_in = None


if __name__ == '__main__':
    from signal import signal, SIGTERM, SIGINT
    shutdown = False

    def signal_handler(signal, frame):
        global shutdown
        shutdown = True
    for signum in (SIGTERM, SIGINT):
        signal(signum, signal_handler)

    while not shutdown:
        try:
            with AndroidOpenAccessoryBridge(
                    *NEXUS4_USB_IDS,
                    manufacturer='AoabManufacturer',
                    model='AoabModel',
                    description='AoabDescription',
                    version=1,
                    uri=('https://github.com/chris-blay/'
                         'android-open-accessory-bridge'),
                    serial='AoabSerial') as aoab:
                aoab.write('0'.encode('utf-8'))
                while not shutdown:
                    bytes = aoab.read()
                    if bytes:
                        value = int(bytes.decode('utf-8'))
                        print('Read in value: {}'.format(value))
                        aoab.write(str(value + 1).encode('utf-8'))
        except usb.core.USBError:
            print('USBError occurred. Restarting…')
