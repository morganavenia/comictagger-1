from __future__ import annotations

from PyQt6.QtGui import QColor, QImage, QPixmap, qRgba

from .icons import icon_path
from .toast_enums import ToastIcon


class IconUtils:

    @staticmethod
    def get_icon_from_enum(enum_icon: ToastIcon) -> QPixmap:
        """Get a QPixmap from a ToastIcon

        :param enum_icon: ToastIcon
        :return: pixmap of the ToastIcon
        """
        image = QPixmap()
        if enum_icon == ToastIcon.SUCCESS:
            image.loadFromData((icon_path / "success.png").read_bytes())
        elif enum_icon == ToastIcon.WARNING:
            image.loadFromData((icon_path / "warning.png").read_bytes())
        elif enum_icon == ToastIcon.ERROR:
            image.loadFromData((icon_path / "error.png").read_bytes())
        elif enum_icon == ToastIcon.INFORMATION:
            image.loadFromData((icon_path / "information.png").read_bytes())
        elif enum_icon == ToastIcon.CLOSE:
            image.loadFromData((icon_path / "close.png").read_bytes())
        return image

    @staticmethod
    def recolor_image(image: QImage, color: QColor | None) -> QImage:
        """Take an image and return a copy with the colors changed

        :param image: image to recolor
        :param color: new color (None if the image should not be recolored)
        :return: recolored image
        """

        # Leave image as is if color is None
        if color is None:
            return image

        # Loop through every pixel
        for x in range(0, image.width()):
            for y in range(0, image.height()):
                # Get current color of the pixel
                current_color = image.pixelColor(x, y)
                # Replace the rgb values with rgb of new color and keep alpha the same
                new_color_r = color.red()
                new_color_g = color.green()
                new_color_b = color.blue()
                new_color = QColor.fromRgba(qRgba(new_color_r, new_color_g, new_color_b, current_color.alpha()))
                image.setPixelColor(x, y, new_color)
        return image
