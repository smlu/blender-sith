# Sith Blender Addon
# Copyright (C) 2019-2026 Crt Vavros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import time

class BenchmarkMeter():
    def __init__(self, text, enabled=True):
        self.text    = text
        self.enabled = enabled
        self.start   = 0.0
    def __enter__(self):
        if self.enabled:
            self.start = time.process_time()
        return self
    def __exit__(self, type, value, traceback):
        if self.enabled:
            print(self.text.format(time.process_time() - self.start))
