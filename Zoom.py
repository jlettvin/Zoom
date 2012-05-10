#!/usr/bin/env python

"""
Zoom.py implements a configurable desktop magnifying glass.
"""

__module__     = "Zoom.py"
__author__     = "Jonathan D. Lettvin"
__copyright__  = "Copyright(c)2012 Jonathan D. Lettvin, All Rights Reserved"
__credits__    = [ "Jonathan D. Lettvin" ]
__license__    = "Unknown"
__version__    = "0.0.1"
__maintainer__ = "Jonathan D. Lettvin"
__email__      = "jlettvin@gmail.com"
__contact__    = "jlettvin@gmail.com"
__status__     = "Prototype"
__date__       = "20120508"

import pygtk
pygtk.require('2.0')

import sys
import cairo
import gobject
import gtk
import gtk.gdk as gdk
import os.path as path

from numpy import zeros, array, rollaxis, dstack, uint8
from pprint import pprint

#AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
class RGB(object):
    """
    RGB enables manipulating normalized ndarrays between
    image acquisition and image display.
    """

    def __init__(self, source):
        """
        Initialize the normalized RGB environment from a pixbuf.
        """
        self.space = source.get_colorspace()
        self.bits  = source.get_bits_per_sample()
        self.source = rollaxis(
                array(source.get_pixels_array(), dtype=float)/256.0, 2, 0)
        self.target = zeros(self.source.shape, dtype=float)

    @property
    def r_source(self):
        """The normalize R source array."""
        return self.source[0, :, :]

    @property
    def g_source(self):
        """The normalize G source array."""
        return self.source[1, :, :]

    @property
    def b_source(self):
        """The normalize B source array."""
        return self.source[2, :, :]

    @property
    def r_target(self):
        """The normalize R target array."""
        return self.target[0, :, :]

    @property
    def g_target(self):
        """The normalize G target array."""
        return self.target[1, :, :]

    @property
    def b_target(self):
        """The normalize B target array."""
        return self.target[2, :, :]

    @property
    def pixbuf(self):
        """The restored pixbuf after the transform (if any)."""
        return gdk.pixbuf_new_from_array(
                array(dstack(self.target)*256.0, dtype=uint8),
                self.space, self.bits)

#BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
class Zoom(object):
    """
    Zoom has a window, and call method as required by gtk.main().
    """

    def __init__(self, **kwargs):
        """__init__ sets up controls for gui interaction."""
        self.basename = path.basename(sys.argv[0])
        self.kwargs   = kwargs

        # Fetch command-line options.
        self.x_size  = self.kwargs.get('x_size' ,   320)
        self.y_size  = self.kwargs.get('y_size' ,   200)
        self.refresh = self.kwargs.get('refresh',    50)
        self.zooming = self.kwargs.get('zoom'   ,     1)
        self.mobile  = self.kwargs.get('mobile' , False)

        # Pre-initialize to satisfy pylint.
        self.cairo   = None
        self.surface = None
        self.source  = None
        self.target  = None
        self.pixbuf  = None
        self.keyfun  = None

        # Initialize various constants and variables.
        mainmask     = gdk.KEY_PRESS_MASK
        self.pre     = [['', ''], ['C-', 'M-']]
        self.mapped  = {'Left': 'h', 'Down': 'j', 'Up': 'k', 'Right': 'l'}

        self.x_win, self.y_win  = 0, 0
        self.x_ctr, self.y_ctr  = 0, 0
        self.x_ptr, self.y_ptr  = 0, 0
        self.m_ptr              = 0
        self.size_change_factor = 1

        self.shft, self.ctrl, self.meta = 0, 0, 0

        # Permitted transform functions.
        self.function = {'invert': self.invert, 'original': self.original}

        # Window initializations.
        self.gtkmain = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.gtkmain.set_decorated(not self.mobile)
        self.gtkmain.set_app_paintable(True)
        self.gtkmain.set_size_request(self.x_size, self.y_size)
        self.gtkmain.set_colormap(self.gtkmain.get_screen().get_rgba_colormap())

        # Event initializations.
        self.gtkmain.connect("destroy"     , gtk.main_quit)
        self.gtkmain.connect('expose-event',          self)

        # Keyboard related initializations.
        self.init_keyboard()
        self.gtkmain.connect("key_press_event", self.key_press_event)
        self.gtkmain.set_events(mainmask)

        # Initialize display to have focus at startup.
        self.gtkmain.set_flags(gtk.HAS_FOCUS | gtk.CAN_FOCUS)
        self.gtkmain.grab_focus()
        gobject.timeout_add(self.refresh, self.timeout)

        # Acquire main gdk window from gtk window.
        self.gtkmain.realize()
        self.gdkmain = self.gtkmain.window
        self.gdkroot = gdk.get_default_root_window()

        # Take dimensions and initialize extents and center.
        self.x_top, self.y_top = self.gdkroot.get_size()
        self.x_max, self.y_max = self.x_top/4, self.y_top/4

        self.change_size_or_position(0, 0)

        self.gtkmain.show()

    def call(self):
        """call"""
        self.cairo = self.gdkmain.cairo_create()
        self.cairo.set_operator(cairo.OPERATOR_CLEAR)
        self.surface = cairo.ImageSurface(
                cairo.FORMAT_ARGB32,
                *self.gtkmain.get_size())
        self.acquire_transform_display()

    def __call__(self, widget, event):
        """__call__"""
        self.change_size_or_position(0, 0)
        return

    def init_keyboard(self):
        """Initialize keyboard function map and hand it off to GTK."""
        self.keyfun = [[self.noop for _ in range(4)] for _ in range(256)]

        for char in '01234': #56789':
            self.keyfun[ord(char)][0] = self.zoom

        self.keyfun[ord('q')][0] = self.quit
        self.keyfun[ord('?')][0] = self.help

        # Window resize or move by 1 or 8 pixel width.
        for group in range(3):
            self.keyfun[ord('h')][group] = self. left_arrow
            self.keyfun[ord('j')][group] = self.   up_arrow
            self.keyfun[ord('k')][group] = self. down_arrow
            self.keyfun[ord('l')][group] = self.right_arrow

    def constrain_mouse(self):
        """Keep acquired image within screen range."""
        self.x_ctr = min(
                max(
                    self.x_ptr - self.x_max/(2*self.zooming),
                    0),
                self.x_top-self.x_max/self.zooming-1)
        self.y_ctr = min(
                max(self.y_ptr - self.y_max/(2*self.zooming),
                    0),
                self.y_top-self.y_max/self.zooming-1)

    def acquire(self):
        """Acquire screen image."""
        self.pixbuf = gdk.Pixbuf(
                gdk.COLORSPACE_RGB,
                False,
                8,
                self.x_max,
                self.y_max)
        self.pixbuf = self.pixbuf.get_from_drawable(
                self.gdkroot,
                self.gdkroot.get_colormap(),
                int(self.x_ctr),
                int(self.y_ctr),
                0,
                0,
                int(self.x_max),
                int(self.y_max))

    def scale_image(self):
        """Scale image according to zooming."""
        self.source = self.pixbuf.scale_simple(
                int(self.x_max * self.zooming),
                int(self.y_max * self.zooming),
                gdk.INTERP_NEAREST)

    def display(self):
        """Paint transformed image into window."""
        self.cairo.set_operator(cairo.OPERATOR_SOURCE)
        self.cairo.set_source_pixbuf(self.target, 0, 0)
        self.cairo.paint()

    def follow(self):
        """Window mouse following function"""
        self.gtkmain.move(self.x_ptr, self.y_ptr)

    def background(self):
        """Paint window when mouse moves window."""
        self.cairo.set_operator(cairo.OPERATOR_SOURCE)

        self.x_ctr = min(
                max(self.x_ptr - self.x_max/2, 0),self.x_top-self.x_max-1)
        self.y_ctr = min(
                max(self.y_ptr - self.y_max/2, 0),self.y_top-self.y_max-1)

        pixbuf = gdk.Pixbuf(
                gdk.COLORSPACE_RGB,
                False,
                8,
                self.x_max,
                self.y_max)
        pixbuf = pixbuf.get_from_drawable(
                self.gdkroot,
                self.gdkroot.get_colormap(),
                self.x_ctr,
                self.y_ctr,
                0,
                0,
                self.x_max,
                self.y_max)

        source = pixbuf.scale_simple(
                int(self.x_max * self.zooming),
                int(self.y_max * self.zooming),
                gdk.INTERP_NEAREST)
        pixarray = source.pixel_array
        minp, maxp = min(pixarray), max(pixarray)
        print minp, maxp

        #TODO transform source into target
        target = source

        self.cairo.set_source_pixbuf(target, 0, 0)
        self.cairo.paint()

    def acquire_transform_display(self):
        """Regular actions to perform on zoom area."""
        self.constrain_mouse()
        if self.mobile:
            self.surface = cairo.ImageSurface(
                    cairo.FORMAT_ARGB32,
                    *self.gtkmain.get_size())
            self.follow()
            self.background()
        else:
            self.acquire()
            self.transform()
            self.display()

    # Keyboard functions for use in keyfun table.
    # Use keyname = gdk.keyval_name(event.keyval) if name is needed.
    def noop(self, an_event):
        """Do nothing."""
        #print an_event.keyval, gdk.keyval_name(an_event.keyval)

    def quit(self, an_event):
        """Quit zoom.py."""
        gtk.main_quit()

    def change_size_or_position(self, a_delta_x, a_delta_y):
        """Modify the window size."""
        factor = 1 + 7 * self.shft
        self.x_max = int(min(
                max(64,
                    self.x_max + a_delta_x * factor),
                self.x_top/2))
        self.y_max = int(min(
                max(64,
                    self.y_max + a_delta_y * factor),
                self.y_top/2))
        #print self.ctrl, self.shft, a_delta_x, a_delta_y
        if self.ctrl:
            self.x_win += a_delta_x * factor
            self.y_win += a_delta_y * factor
            self.gtkmain.move(self.x_win, self.y_win)
        else:
            self.gtkmain.set_size_request(self.x_max, self.y_max)
            self.gtkmain.resize(self.x_max, self.y_max)

    def size_position_change_handler(self, an_event, a_delta_x, a_delta_y):
        """Modify the window size from an event."""
        self.change_size_or_position(a_delta_x, a_delta_y)

    def left_arrow(self, an_event):
        """Change the window horizontally."""
        self.size_position_change_handler(an_event, -1, 0)

    def down_arrow(self, an_event):
        """Change the window vertically."""
        self.size_position_change_handler(an_event, 0, -1)

    def right_arrow(self, an_event):
        """Change the window horizontally."""
        self.size_position_change_handler(an_event, 1, 0)

    def up_arrow(self, an_event):
        """Change the window vertically."""
        self.size_position_change_handler(an_event, 0, 1)

    def zoom(self, an_event):
        """Assign new zoom factor (1+3*k/9)."""
        digit = an_event.keyval - ord('0')
        self.zooming = 1.0 + 3.0 * digit / 9.0
        self.gtkmain.set_title('%s: %f' % (self.basename, self.zooming))

    def help(self, an_event):
        """Display this keyfun doc"""
        for num, series in enumerate(self.keyfun):
            for index, fun in enumerate(series):
                ctrl, meta = (index)&1, (index>>1)&1
                if fun != self.noop:
                    print '%s%s%c\t%s' % (
                            self.pre[ctrl][0],
                            self.pre[meta][1],
                            chr(num),
                            fun.__doc__)
        pprint(self.kwargs)

    # Keyboard service functions
    def accept(self, a_key):
        """Ensure that key is within the original ASCII 128."""
        if a_key > 127:
            return ord(self.mapped.get(gdk.keyval_name(a_key), '$'))
        else:
            return a_key

    def key_press_event(self, a_window, an_event):
        """
        key_press_event gets event meta-information (Ctrl, Meta)
        and runs the keyboard function associated with the key.
        Finally, it updates the visuals.
        """
        self.shft = int(0 != (an_event.state&gdk.  SHIFT_MASK))
        self.ctrl = int(0 != (an_event.state&gdk.CONTROL_MASK))
        self.meta = int(0 != (an_event.state&gdk.   MOD1_MASK))
        mask = 1*self.ctrl + 2*self.meta
        self.keyfun[self.accept(an_event.keyval)][mask](an_event)
        self(a_window, an_event)
        return True

    # Mouse position polling function.
    def timeout(self):
        """
        gtk, wx, and other libraries fail to support out-of-window mousing.
        This idle function is used to locate the mouse.
        """
        self.x_ptr, self.y_ptr, self.m_ptr = self.gdkroot.get_pointer()
        self.x_win, self.y_win             = self.gtkmain.get_position()
        self.call()
        return True

    def original(self, rgb):
        """Leave image intact"""
        rgb.r_target[:, :] = rgb.r_source[:, :]
        rgb.g_target[:, :] = rgb.g_source[:, :]
        rgb.b_target[:, :] = rgb.b_source[:, :]

    def invert(self, rgb):
        """Invert the image colors (1.0-source)"""
        rgb.r_target[:, :] = 1.0-rgb.r_source[:, :]
        rgb.g_target[:, :] = 1.0-rgb.g_source[:, :]
        rgb.b_target[:, :] = 1.0-rgb.b_source[:, :]

    def operate(self, fun):
        """Run filter on normalized color planes."""
        # TODO transform source pixbuf into target pixbuf
        # The array is 3 planes (not 4 with alpha).
        # Modify contents, leaving framework intact.
        rgb = RGB(self.source)
        fun(rgb)
        self.target = rgb.pixbuf

    def transform(self):
        """Convert input window data to output window data."""
        self.scale_image()
        self.operate(self.function[self.kwargs['transform']])

#CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
if __name__ == "__main__":
    def constrain(low, value, high):
        """Check that a value is within a specified range."""
        assert low <= value <= high

    from optparse import OptionParser

    usage = """ zoom.py
    creates an interactive dynamic window
    containing a copy of a desktop region
    around the mouse with options for
    zooming and transforming the image.
    """
    parser = OptionParser(usage=usage)
    parser.add_option(
            '-f', '--filter',
            type=str,
            default='target=1.0-source',
            help    = 'command-line filter math')
    parser.add_option(
            '-t', '--transform',
            type=str,
            default='original',
            help    = 'image transforms (original, invert)')
    parser.add_option(
            '-m', '--mobile',
            action='store_true',
            default=False,
            help    = 'window follows mouse')
    parser.add_option(
            '-r', '--refresh',
            type    = int,
            default = 200,
            help    = 'timer refresh rate')
    parser.add_option(
            '-x', '--x_size',
            type    = int,
            default = 100,
            help    = 'initial width of window')
    parser.add_option(
            '-y', '--y_size',
            type    = int,
            default = 100,
            help    = 'initial height of window')
    parser.add_option(
            '-z', '--zoom',
            type    = int,
            default = 1,
            help    = 'zoom factor')

    opts, args = parser.parse_args()
    prms = vars(opts)

    constrain(16, prms['x_size' ], 640)
    constrain(16, prms['y_size' ], 640)
    constrain( 1, prms['refresh'], 500)
    constrain( 1, prms['zoom'   ],   4)

    Zoom(**prms)
    gtk.main()
