import 'package:geocoding/geocoding.dart';
import 'package:geolocator/geolocator.dart';

class LocationService {
  static Future<bool> ensurePermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) return false;
    var p = await Geolocator.checkPermission();
    if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
    return p == LocationPermission.always || p == LocationPermission.whileInUse;
  }

  static Future<Position?> current() async {
    if (!await ensurePermission()) return null;
    try {
      return await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high))
          .timeout(const Duration(seconds: 8));
    } catch (_) {
      return Geolocator.getLastKnownPosition();
    }
  }

  /// Human label for a location tag ("Nelson-Atkins Museum of Art", "Columbia").
  static Future<String?> placeName(double lat, double lng) async {
    try {
      final marks = await placemarkFromCoordinates(lat, lng);
      if (marks.isEmpty) return null;
      final m = marks.first;
      final parts = [m.name, m.locality].where((s) => s != null && s.isNotEmpty && !RegExp(r'^\d').hasMatch(s)).toSet();
      return parts.isEmpty ? m.locality : parts.join(', ');
    } catch (_) {
      return null;
    }
  }

  static double distanceM(double lat1, double lng1, double lat2, double lng2) => Geolocator.distanceBetween(lat1, lng1, lat2, lng2);
}
