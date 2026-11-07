from PyQt6.QtCore import Qt, QRectF, QPointF, QPoint
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
import pyqtgraph as pg
import numpy as np
from pyqtgraph import PlotDataItem, mkPen, ROI

class CurveDigitizer:
    def __init__(self):
        self.points = []
        self.ignored_points = set()

    def extract_curve(self, image_array, graph_roi, x_scale=None, y_scale=None):
        """
        Extracts curve points from a digitized region

        Args:
            image_array (numpy.ndarray): Input image array
            graph_roi (ROI): Region of Interest where the curve is drawn
            x_scale (float, optional): X-axis scaling factor. Defaults to None.
            y_scale (float, optional): Y-axis scaling factor. Defaults to None.

        Returns:
            list: List of [x, y] points along the curve
        """
        if not all([x_scale, y_scale]):
            # Auto-detect scale from selected ROI position
            graph_roi.setAllowMove(False)
            x_scale = self.get_axis_scale(image_array.shape[1],
                                        np.min(graph_roi.getState()['pos'][0]),
                                        np.max(graph_roi.getState()['pos'][0]))
            y_scale = self.get_axis_scale(image_array.shape[0],
                                        np.min(graph_roi.getState()['pos'][1]),
                                        np.max(graph_roi.getState()['pos'][1]))

        # Convert ROI coordinates to graph coordinates
        curve_points = []
        for point in graph_roi.getState().get('points', []):
            if not (point['x'], point['y']) in self.ignored_points:
                x_graph = self.scale_point(point['x'] + 0.5, image_array.shape[1],
                                            np.min(graph_roi.getState()['pos'][0]),
                                            x_scale)
                y_graph = self.scale_point(point['y'] + 0.5, image_array.shape[0],
                                            np.min(graph_roi.getState()['pos'][1]),
                                            y_scale)
                curve_points.append([x_graph, y_graph])

        return curve_points

    def get_axis_scale(self, axis_size, min_val, max_val):
        """Calculates appropriate scaling factor for the axes"""
        # Convert pixel measurements to numerical values based on ROI position
        if min_val == max_val:
            return 1.0 / (axis_size // 2)
        else:
            return ((max_val - min_val) * axis_size) / (np.log(max_val + 1))

    def scale_point(self, point_value, array_size, base_point, scale):
        """Scales a pixel position to graph coordinates"""
        # Adjusts for the actual image dimensions and ROI position
        if array_size <= 0:
            return point_value

        adjusted_base = np.log(base_point + 1) if base_point < 0 else base_point

        try:
            x_graph = ((point_value - adjusted_base) * (array_size // scale)) / (np.log(array_size//2 + 1))
            return max(min(x_graph, array_size), 0)
        except ZeroDivisionError:
            # Handle special cases where scaling might be problematic
            return point_value

    def draw_curve(self, points):
        """Draws the curve on the graph using PyqtGraph"""
        if len(points) < 2:
            print("Need at least two points to form a curve")
            return None

        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]

        # Sort points by X-coordinate
        sorted_points = sorted(zip(x_coords, y_coords), key=lambda point: point[0])

        self.points.extend(sorted_points)
        return PlotDataItem(
            data=[x_val for x_val, _ in sorted_points],
            symbol='o',
            pen=mkPen(color='#FF0000', width=2),
            brush={'color': '#FF0000'})

class MaskPainter():
    def __init__(self):
        self.autoDetector = None

    def onRedraw(self, image_item: pg.ImageItem, graph_data: list):
        """Updates the mask display based on detected data"""

        # Get mask information from auto detector
        if not self.autoDetector or (not hasattr(self.autoDetector, 'mask') or
                                    not hasattr(self.autoDetector.mask, 'size')):
            return

        # Update pixel colors at masked positions
        img_data = image_item.image()
        for idx in self.autoDetector.mask:
            r, g, b, a = QColor.fromHsv(0, 0, int(idx/256*255)).rgba()[:4]
            img_data[idx] = [r, g, b, a]


class PenMaskTool():
    def __init__(self):
        self.ctx = None
        self.isDrawing = False
        self.lastPos = QPoint()

    @staticmethod
    def getActiveDataset(graph_widget):
        """Returns active dataset from the graph widget"""
        # This would need to be implemented based on your specific data structure

    def onAttach(self, graph_widget: pg.GraphicsLayoutWidget):
        """Initializes the mask tool when attached to the graph"""
        self.ctx = graph_widget.getAllContexts()
        self.autoDetector = graph_widget.getAutoDetectionDataForDataset(
            PenMaskTool.getActiveDataset(graph_widget))

        # Create a transparent ImageItem for masking
        self.mask_image = pg.ImageItem(np.zeros((graph_widget.scene().sceneRect().height(),
                                                graph_widget.scene().sceneRect().width()),
                                                levels=None))
        self.mask_image.setOpacity(0.5)  # Make it semi-transparent
        self.mask_image.setZValue(-1)

        # Connect mouse event handlers
        self.ctx.scene().sigMouseMoved.connect(self.mouseMoveHandler)

    def onMouseDown(self, pos: QPoint):
        """Handles mouse down for starting mask drawing"""
        if not hasattr(self.ctx, 'dataCtx') or not hasattr(self.ctx.oriDataCtx, 'Image'):
            return

        self.isDrawing = True
        self.lastPos = pos

        # Create XOR-style brush effect using two ImageItems
        brush_thickness = 3 * self.ctx.getZoomRatio()  # Scale with zoom level

        # Draw on mask image (not visible) and original data (visible)
        self.ctx.dataCtx.setPen(QPen(Qt.GlobalColor.red, int(brush_thickness), Qt.PenStyle.SolidLine))
        self.ctx.dataCtx.moveTo(pos.x(), pos.y())

    def mouseMoveHandler(self, scene_pos: QPointF):
        """Handles drawing during mouse movement"""
        if not self.isDrawing:
            return

        # Get canvas position
        canvas_pos = self.ctx.screenToCanvasPx(scene_pos.x(), scene_pos.y())

        # Update both the mask and original data with XOR effect
        self.ctx.dataCtx.globalCompositeOperation = "xor"
        self.ctx.oriDataCtx.globalCompositeOperation = "xor"

        self.ctx.dataCtx.lineTo(canvas_pos.x, canvas_pos.y)
        self.ctx.dataCtx.stroke()

        # Also update on the displayed image (mask_image)
        mask_canvas_pos = self.ctx.screenToCanvasPx(
            scene_pos.x() + self.mask_offset_x,
            scene_pos.y() + self.mask_offset_y
        )

        self.ctx.oriDataCtx.lineTo(mask_canvas_pos.x, mask_canvas_pos.y)
        self.ctx.oriDataCtx.stroke()

        # Reset composite operations after drawing
        self.ctx.dataCtx.globalCompositeOperation = "source-over"
        self.ctx.oriDataCtx.globalCompositeOperation = "source-over"

    def onMouseUp(self):
        """Handles mouse up for finishing mask drawing"""
        self.isDrawing = False

        # Finalize the mask by capturing all points drawn in this session
        if hasattr(self.autoDetector, 'grabMask'):
            self.autoDetector.grabMask()

class DigitizedCurve():

    @staticmethod
    def getXYFromScreenPos(plot_widget):
        """Converts screen coordinates to graph data coordinates"""
        # Get image dimensions and current zoom level

        # Calculate pixel density based on plot widget size

        # Apply scaling factors from the auto detector

        return converted_points


# Example of how these might be integrated into your main window
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.graphWidget = pg.GraphicsLayoutWidget()

        # Initialize mask tools
        self.pen_mask_tool = PenMaskTool()
        self.erase_mask_tool = EraseMaskTool()

        # Connect signals and slots for the GUI

    def setupUi(self, *args, **kwargs):
        """Sets up the UI with necessary components"""
        super().setupUi(*args, **kwargs)

        # Set up auto detection system
        self.auto_detector = AutoDetectionSystem()

        # Add buttons to toggle mask tools
        self.btn_pen_mask.clicked.connect(self.togglePenMaskTool)
        self.btn_erase_mask.clicked.connect(self.toggleEraseMaskTool)

    def togglePenMaskTool(self, enable=True):
        """Toggles the pen mask tool on/off"""
        if enable:
            self.pen_mask_tool.onAttach(self.graphWidget)
        else:
            self.erase_mask_tool = None
            # Cleanup operations to remove mask effects

    def loadGraphImage(self, file_path):
        """Loads a graph image and prepares for digitization"""
        # Load the image into PyQt5

        # Create an ImageItem for display

        # Initialize auto detection system with this image

class AutoDetectionSystem():

    def __init__(self):
        self.mask = set()  # Stores positions where mask should be applied
        self.Xmin, self.Xmax, self.Ymin, self.Ymax = None, None, None, None

    def detectGridLines(self, image_array):
        """Detects grid lines in the graph"""

        # Use edge detection and Hough transform to find grid lines

        return detected_grid_lines

    def getAutoDetectionDataForDataset(self, dataset):
        """Returns auto-detection data for a given dataset"""

        if not self.detected or (self.Xmin is None and self.Ymin is None):
            # Perform automatic detection
            self.detectGridLines(image_array)

        return {
            'Xmin': self.Xmin,
            'Xmax': self.Xmax,
            'Ymin': self.Ymin,
            'Ymax': self.Ymax,
            'mask': self.mask
        }

    def grabMask(self):
        """Grabs the mask data from the image"""

        # Convert the drawn mask to graph coordinates

        return masked_data

# Note: This is a simplified implementation focusing on the key concepts.
# The actual implementation would need to handle:
#   - Proper coordinate transformations between screen and canvas
#   - Image scaling with zoom level
#   - Saving the detected data for later use in your application

class GraphGridDetector():
    def __init__(self):
        self.detected_grid = None

    @staticmethod
    def find_edges(image_array):
        """Detect edges in the image using Canny edge detector"""
        gray = cv2.cvtColor(image_array.astype('uint8'), cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 100, 200)

        return edges

    @staticmethod
    def find_grid_lines(edges):
        """Detect grid lines using Hough Transform"""
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50,
                                minLineLength=30, maxLineGap=20)

        if lines is None:
            return []

        # Filter only horizontal and vertical grid lines
        grid_lines = [line[0] for line in lines if
                        (abs(line[0][0]-line[0][2]) > 5 or abs(line[0][1]-line[0][3]) > 5)]

        return sorted(grid_lines, key=lambda x: (x[0]+x[2])/2)  # Sort by average X position

    def detect_grid(self, image_array):
        """Detect grid boundaries from the graph"""
        edges = self.find_edges(image_array)
        grid_points = []

        for y in range(10, image_array.shape[0], 30):  # Sample every few pixels
            row = np.sum(image_array[y], axis=1) / np.max(np.sum(image_array[y], axis=1))
            x_indices = [x//2 for x in np.where(row > 0.5)[0]]  # Find where sum is significant

            if len(x_indices) > 5:  # More than half the screen should be grid
                avg_x = np.mean([x for i,x in enumerate(x_indices)
                                if abs(i-len(x_indices)/2)>len(x_indices)/4])

                if y < image_array.shape[0] and (avg_x, y) not in self.detected_grid:
                    grid_points.append((avg_x, y))

        # Use clustering to find the four corners of the graph
        from sklearn.cluster import DBSCAN

        clusterer = DBSCAN(eps=5, min_samples=3)
        xy = np.array([[p[0], p[1]] for p in grid_points])
        clusters = clusterer.fit_predict(xy)

        # Get one point per cluster and add to detected_grid
        unique_clusters = {}
        for i,p in enumerate(grid_points):
            if not any(c == 0 or c != -1 for c in clusters[i:i+5]):
                continue

            cluster_id = clusters[i]
            if cluster_id not in unique_clusters:
                unique_clusters[cluster_id] = p
            else:
                # Average the points in each cluster to get more accurate corners
                unique_clusters[cluster_id] = np.mean([unique_clusters[cluster_id],p], axis=0)

        # Now we have four corner points, let's define our grid ROI
        x_min,y_min = min(unique_clusters.values(), key=lambda p:p[0])
        x_max,y_max = max(unique_clusters.values(), key=lambda p:p[0]) if unique_clusters else image_array.shape[1]

        self.detected_grid = (x_min, y_min, x_max, y_max)

    def draw_roi(self, plot_widget):
        """Draw the detected grid ROI on the plot"""
        if not all([self.detected_grid]):
            return

        # Convert grid coordinates to graph coordinates
        from PIL import Image

        roi = pg.RectROI(
            pos=(self.detected_grid[0], self.detected_grid[1]),
            size=(self.detected_grid[2]-self.detected_grid[0],
            self.detected_grid[3]-self.detected_grid[1]),
            pen=pg.mkPen(color='g', width=2),
            removable=False
        )

        plot_widget.addItem(roi)
