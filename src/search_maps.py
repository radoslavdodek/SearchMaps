#!/usr/bin/env python3
import json
import math
import sys
import time
import webbrowser

import requests
from PySide6.QtCore import QObject, Slot, Signal
from PySide6.QtCore import QSettings
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFormLayout,
    QMessageBox, QGroupBox
)
from PySide6.QtWidgets import QDialog, QDialogButtonBox
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWidgets import QTableWidget, QHeaderView
from PySide6.QtWidgets import QTableWidgetItem

LEAFLET_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>OpenStreetMap with Leaflet</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        html, body {
            height: 100%;
            margin: 0;
            padding: 0;
        }
        #map {
            width: 100%;
            height: 100vh;
            min-height: 100%;
        }
        #center-x {
            position: absolute;
            left: 50%;
            top: 50%;
            width: 24px;
            height: 24px;
            margin-left: -12px;
            margin-top: -12px;
            z-index: 999;
            pointer-events: none;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .x-line {
            position: absolute;
            width: 24px;
            height: 1px;
            background: #0078ff;
            left: 0;
            top: 50%;
            opacity: 0.85;
        }
        .x-line.first {
            transform: rotate(45deg);
        }
        .x-line.second {
            transform: rotate(-45deg);
        }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
</head>
<body>
<div id="map"></div>
<div id="center-x">
    <div class="x-line first"></div>
    <div class="x-line second"></div>
</div>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
    var initialCenter = [48.8584, 2.2945];
    var initialZoom = 5;
    var map = L.map('map').setView(initialCenter, initialZoom);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    var radiusMeters = 50000;
    var centerCircle = L.circle(map.getCenter(), {
        color: 'blue',
        fillColor: '#30f',
        fillOpacity: 0.08,
        radius: radiusMeters
    }).addTo(map);

    map.on('move', function () {
        centerCircle.setLatLng(map.getCenter());
        updatePythonCenter();
    });

    function updatePythonCenter() {
        if (window.bridge) {
            var c = map.getCenter();
            var z = map.getZoom();
            window.bridge.setCenterAndZoom(c.lat, c.lng, z);
        }
    }

    map.on('move', updatePythonCenter);
    map.on('zoom', updatePythonCenter);

    // QWebChannel setup
    new QWebChannel(qt.webChannelTransport, function (channel) {
        window.bridge = channel.objects.bridge;
        // Send initial center
        updatePythonCenter();
    });

    // Add a function to set map view from Python
    window.setMapView = function (lat, lng, zoom) {
        map.setView([lat, lng], zoom);
    }

    // Add a function to set radius from Python
    window.setCircleRadius = function (radius) {
        radiusMeters = radius;
        centerCircle.setRadius(radius);
    }
</script>
</body>
</html>
"""


class ResultsTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_ui = parent  # Reference to SearchMapsUI

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            selected = self.selectedIndexes()
            if selected:
                row = selected[0].row()
                if self._parent_ui:
                    self._parent_ui.open_place_in_maps(row)
            return  # Prevent default
        super().keyPressEvent(event)


class MapBridge(QObject):
    centerChanged = Signal(float, float, int)  # latitude, longitude, zoom

    def __init__(self):
        super().__init__()
        self.latitude = 48.8584
        self.longitude = 2.2945
        self.zoom = 5

    @Slot(float, float, int)
    def setCenterAndZoom(self, lat, lng, zoom):
        self.latitude = lat
        self.longitude = lng
        self.zoom = zoom
        self.centerChanged.emit(lat, lng, zoom)


class SearchMapsUI(QMainWindow):
    """Main UI class for the SearchMaps application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Search Maps")
        self.setMinimumSize(1000, 800)
        self.provider_name = ""
        self.selected_row = None
        self.setup_ui()

    def setup_ui(self):
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Create left column layout
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)

        # Create input form
        input_group = QGroupBox()
        input_layout = QFormLayout()

        self.fetch_button = QPushButton("Search")

        self.search_query_edit = QLineEdit()
        self.search_query_edit.setPlaceholderText("Enter search query (e.g. restaurant)")
        self.search_query_edit.returnPressed.connect(self.fetch_button.click)
        input_layout.addRow("Search Query:", self.search_query_edit)

        # Radius selection input (above the map)
        from PySide6.QtWidgets import QSpinBox
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(1, 50)
        self.radius_spin.setValue(50)
        self.radius_spin.setSuffix(" km")
        self.radius_spin.setSingleStep(1)
        input_layout.addRow("Radius:", self.radius_spin)

        # Add OpenStreetMap widget
        self.map_view = QWebEngineView()
        self.map_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.map_view.setHtml(LEAFLET_HTML)
        input_layout.addRow(self.map_view)

        self.map_bridge = MapBridge()
        self.map_channel = QWebChannel()
        self.map_channel.registerObject("bridge", self.map_bridge)
        self.map_view.page().setWebChannel(self.map_channel)

        self.radius_spin.valueChanged.connect(self.update_map_radius)

        # Fetch/Search and Settings buttons in one row
        fetch_button_layout = QHBoxLayout()

        # Search button fills all available space
        self.fetch_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fetch_button_layout.addWidget(self.fetch_button)
        self.fetch_button.clicked.connect(self.on_fetch_button_clicked)

        # Settings button as a small gear icon
        self.settings_button = QPushButton()
        self.settings_button.setToolTip("Set Google Maps API Key")
        self.settings_button.setFixedSize(28, 28)
        self.settings_button.setText("⚙️")
        self.settings_button.clicked.connect(self.show_settings_dialog)
        fetch_button_layout.addWidget(self.settings_button)

        input_layout.addRow("", fetch_button_layout)

        # Status
        self.status_label = QLabel("")
        input_layout.addRow("", self.status_label)

        input_group.setLayout(input_layout)
        left_layout.addWidget(input_group)
        left_layout.addWidget(self.map_view, stretch=1)

        # Add left column to main layout
        main_layout.addWidget(left_column)

        self.result_dialog = None

        # Create right column with results table
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)

        # Create the results table
        self.results_table = ResultsTableWidget(self)
        self.results_table.cellClicked.connect(self.on_table_row_clicked)
        self.results_table.cellDoubleClicked.connect(self.on_table_row_double_clicked)
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels([
            "#", "Place name", "Rating", "Reviews count", "Address"
        ])
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Place name
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Rating
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Reviews count
        header.setSectionResizeMode(4, QHeaderView.Stretch)  # Address
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # "#" column

        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        right_layout.addWidget(self.results_table)

        # Make the table fill the right layout
        right_column.setLayout(right_layout)

        # Add left and right columns to main layout, each taking half the width
        main_layout.addWidget(left_column, stretch=1)
        main_layout.addWidget(right_column, stretch=2)

        self.map_view.loadFinished.connect(self.on_map_load_finished)

    def on_table_row_clicked(self, row, column):
        self.selected_row = row

    def show_settings_dialog(self):
        # Load current key from settings
        settings = QSettings("YourCompany", "SearchMaps")
        current_key = settings.value("api_key", "")
        dialog = ApiKeyDialog(self, api_key=current_key)
        if dialog.exec() == QDialog.Accepted:
            new_key = dialog.get_api_key()
            settings.setValue("api_key", new_key)
            self.api_key = new_key

    def open_place_in_maps(self, row):
        item = self.results_table.item(row, 1)
        if item:
            place_id = item.data(1000)
            if place_id:
                url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
                webbrowser.open(url)
                return

        # Fallback: try coordinates
        if not hasattr(self, "last_places"):
            return
        if row >= len(self.last_places):
            return
        place = self.last_places[row]
        location = place.get("location", {})
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is not None and lng is not None:
            url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
            webbrowser.open(url)

    def on_map_load_finished(self, ok):
        if ok:
            self.restore_settings()

    def on_table_row_double_clicked(self, row, column):
        self.selected_row = row
        self.open_place_in_maps(row)

    def on_fetch_button_clicked(self):
        settings = QSettings("YourCompany", "SearchMaps")
        api_key = settings.value("api_key", "")
        if not api_key:
            self.show_error("API key is not set. Please set it in Settings.")
            return

        # Show loading status and disable button
        self.status_label.setText("Loading...")
        self.fetch_button.setEnabled(False)
        QApplication.processEvents()  # Force UI update

        search_string = self.search_query_edit.text().strip()
        latitude = self.map_bridge.latitude
        longitude = self.normalize_longitude(self.map_bridge.longitude)
        radius = self.radius_spin.value() * 1000  # in meters

        print(
            f"[Action] Searching with query='{search_string}', lat={latitude}, lng={longitude}, radius={radius}")

        original_order, places, error = self.google_maps_text_search(
            api_key=api_key,
            search_string=search_string,
            latitude=latitude,
            longitude=longitude,
            radius=radius,
            min_reviews=0
        )
        if error:
            self.show_error(error)
            self.status_label.setText("")
            self.fetch_button.setEnabled(True)
            return

        self.last_places = places
        self.last_places_original_order = original_order  # Save for later use

        print(f"[Result] Fetched {len(places)} places")

        self.update_results_table(places, original_order)

        # Clear loading status and re-enable button
        self.status_label.setText("")
        self.fetch_button.setEnabled(True)

    def google_maps_text_search(self, api_key, search_string, latitude, longitude, radius=30000.0, min_reviews=0):
        """
        Searches Google Maps for places matching the search string near the given latitude and longitude.
        Returns a list of places with displayName, formattedAddress, rating, userRatingCount, location, and plusCode.
        """
        url = "https://places.googleapis.com/v1/places:searchText"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.displayName,"
                "places.formattedAddress,"
                "places.rating,"
                "places.userRatingCount,"
                "places.location,"
                "places.plusCode,"
                "places.id,"
                "nextPageToken"
            )
        }

        body = {
            "textQuery": search_string,
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": float(latitude),
                        "longitude": float(longitude)
                    },
                    "radius": float(radius)
                }
            },
            "maxResultCount": 20
        }

        places = []
        while True:
            response = requests.post(url, headers=headers, json=body)

            if response.status_code != 200:
                error_msg = f"Error: {response.status_code} - {response.text}"
                print(error_msg)
                return None, error_msg

            data = response.json()

            if 'places' in data:
                for place in data['places']:
                    rating_count = place.get('userRatingCount', 0)
                    if rating_count >= min_reviews:
                        # Extract plusCode if available
                        plus_code = place.get('plusCode', {}).get('globalCode', 'N/A')
                        place['plusCodeValue'] = plus_code
                        places.append(place)

            if 'nextPageToken' not in data:
                break

            time.sleep(2)
            body['pageToken'] = data['nextPageToken']

        original_order = list(places)  # Make a copy of the original order

        # Filter places by distance from center
        filtered_places = []
        for place in places:
            loc = place.get('location', {})
            plat = loc.get('latitude')
            plon = loc.get('longitude')
            if plat is not None and plon is not None:
                dist = haversine_distance(latitude, longitude, plat, plon)
                if dist <= radius:
                    filtered_places.append(place)

        # Sort by number of reviews (descending), then by review score (descending)
        filtered_places.sort(key=lambda p: (-p.get('userRatingCount', 0), -p.get('rating', 0)))

        return original_order, filtered_places, None

    def update_map_radius(self, value):
        # value is in km, convert to meters
        radius_m = value * 1000
        js = f"""
            if (typeof centerCircle !== 'undefined') {{
                centerCircle.setRadius({radius_m});
            }}
            if (typeof window.setCircleRadius === 'function') {{
                window.setCircleRadius({radius_m});
            }}
        """
        self.map_view.page().runJavaScript(js)

    def normalize_longitude(self, lon):
        """Normalize longitude to the range [-180, 180]."""
        return ((lon + 180) % 360) - 180

    def update_results_table(self, places, original_order=None):
        self.results_table.setRowCount(len(places))
        n = len(original_order) if original_order else len(places)
        # Map place id to its original index
        id_to_index = {}
        if original_order:
            for idx, place in enumerate(original_order):
                pid = place.get('id', None)
                if pid:
                    id_to_index[pid] = idx

        for row, place in enumerate(places):
            name = place.get('displayName', {}).get('text', '')
            rating = str(place.get('rating', ''))
            reviews = str(place.get('userRatingCount', ''))
            address = place.get('formattedAddress', '')
            place_id = place.get('id', '')

            # Use original order for relevance
            if original_order and place_id in id_to_index:
                orig_idx = id_to_index[place_id]
                if n > 1:
                    relevance = 1.0 - (orig_idx / (n - 1))
                else:
                    relevance = 1.0
                r_text = str(orig_idx + 1)
            else:
                # fallback: use current row
                if n > 1:
                    relevance = 1.0 - (row / (n - 1))
                else:
                    relevance = 1.0
                r_text = str(row + 1)

            # Interpolate color: green (most relevant) to red (least relevant)
            r = int(255 * (1 - relevance))
            g = int(255 * relevance)
            b = 0
            color = QColor(r, g, b, 80)

            relevance_item = QTableWidgetItem(r_text)
            relevance_item.setBackground(color)
            self.results_table.setItem(row, 0, relevance_item)

            item_name = QTableWidgetItem(name)
            item_name.setData(1000, place_id)
            self.results_table.setItem(row, 1, item_name)
            self.results_table.setItem(row, 2, QTableWidgetItem(rating))
            self.results_table.setItem(row, 3, QTableWidgetItem(reviews))
            self.results_table.setItem(row, 4, QTableWidgetItem(address))

    def show_error(self, message):
        """Display an error message dialog."""
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        settings = QSettings("YourCompany", "SearchMaps")
        settings.setValue("search_query", self.search_query_edit.text())
        settings.setValue("radius", self.radius_spin.value())
        settings.setValue("latitude", self.map_bridge.latitude)
        settings.setValue("longitude", self.map_bridge.longitude)
        settings.setValue("zoom", self.map_bridge.zoom)
        # Save table data (places)
        places_json = json.dumps(getattr(self, "last_places", []))
        settings.setValue("places", places_json)
        original_order_json = json.dumps(getattr(self, "last_places_original_order", []))
        settings.setValue("places_original_order", original_order_json)
        # Save selected row
        selected = self.results_table.currentRow()
        settings.setValue("selected_row", selected)

        event.accept()

    def restore_settings(self):
        settings = QSettings("YourCompany", "SearchMaps")
        self.search_query_edit.setText(settings.value("search_query", ""))
        self.radius_spin.setValue(int(settings.value("radius", 50)))
        lat = float(settings.value("latitude", 48.8584))
        lng = float(settings.value("longitude", 2.2945))
        zoom = int(settings.value("zoom", 5))
        self.map_bridge.latitude = lat
        self.map_bridge.longitude = lng
        self.map_bridge.zoom = zoom
        # Set map view via JS
        js = f"window.setMapView({lat}, {lng}, {zoom});"
        self.map_view.page().runJavaScript(js)

        # Restore table data (places)
        places_json = settings.value("places", "")
        original_order_json = settings.value("places_original_order", "")
        original_order = None
        if original_order_json:
            try:
                original_order = json.loads(original_order_json)
                self.last_places_original_order = original_order
            except Exception as e:
                print(f"Failed to restore original order: {e}")
        if places_json:
            try:
                places = json.loads(places_json)
                self.last_places = places
                self.update_results_table(places, original_order)
            except Exception as e:
                print(f"Failed to restore places: {e}")

        selected_row = settings.value("selected_row", None)
        if selected_row is not None:
            try:
                selected_row = int(selected_row)
                if 0 <= selected_row < self.results_table.rowCount():
                    self.results_table.setCurrentCell(selected_row, 0)
                    self.selected_row = selected_row
            except Exception as e:
                print(f"Failed to restore selected row: {e}")

        self.api_key = settings.value("api_key", "")


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points (in meters)."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class ApiKeyDialog(QDialog):
    """Dialog to enter the Google Maps API key."""

    def __init__(self, parent=None, api_key=""):
        super().__init__(parent)
        self.setWindowTitle("API Key Settings")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        self.label = QLabel("Enter your Google Maps API Key:")
        layout.addWidget(self.label)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setText(api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.api_key_edit)

        self.show_key_checkbox = QPushButton("Show/Hide Key")
        self.show_key_checkbox.setCheckable(True)
        self.show_key_checkbox.setChecked(False)
        self.show_key_checkbox.toggled.connect(self.toggle_show_key)
        layout.addWidget(self.show_key_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def toggle_show_key(self, checked):
        self.api_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def get_api_key(self):
        return self.api_key_edit.text().strip()


def main():
    QApplication.setApplicationName("Search Maps")
    app = QApplication(sys.argv)

    window = SearchMapsUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
