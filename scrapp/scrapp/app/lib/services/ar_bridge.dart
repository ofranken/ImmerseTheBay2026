import 'package:flutter/services.dart';

import '../models.dart';

/// One thing to show in AR (a shared sticker, or a hunt item).
class ArItem {
  ArItem({required this.id, required this.imageUrl, required this.anchor, this.title, this.targetUrl});
  final String id;
  final String imageUrl;
  final AnchorSpec anchor;
  final String? title;
  final String? targetUrl; // reference photo for image anchoring (hunt artwork)

  Map<String, dynamic> toMap() => {
        'id': id,
        'imageUrl': imageUrl,
        'title': title,
        'targetUrl': targetUrl,
        'anchor': anchor.toJson(),
      };
}

/// Opens the native ARCore activity (android/.../ar/ScrappArActivity.kt).
class ArBridge {
  static const _m = MethodChannel('scrapp/ar');

  /// Returns the ids of items that were found/anchored during the session.
  static Future<List<String>> open({required List<ArItem> items, required String title, String? instructions}) async {
    final r = await _m.invokeMethod<List<dynamic>>('open', {
      'title': title,
      'instructions': instructions,
      'items': items.map((e) => e.toMap()).toList(),
    });
    return (r ?? []).map((e) => e.toString()).toList();
  }

  /// Shows a whole collage (stickers + 3D models, see services/collage_ar.dart) placed on a table, floor or wall.
  static Future<void> openCollage({required String title, required List<Map<String, dynamic>> items}) =>
      _m.invokeMethod<List<dynamic>>('openCollage', {'title': title, 'items': items});

  static Future<bool> available() async => await _m.invokeMethod<bool>('available') ?? false;
}

/// COCO labels the on-device detector (EfficientDet-Lite0) knows; offered when anchoring to objects.
const anchorObjectClasses = [
  'apple', 'banana', 'orange', 'broccoli', 'carrot', 'donut', 'cake', 'sandwich',
  'cup', 'bottle', 'wine glass', 'bowl', 'book', 'potted plant', 'vase', 'clock',
  'chair', 'couch', 'bed', 'dining table', 'laptop', 'cell phone', 'keyboard', 'mouse',
  'tv', 'teddy bear', 'backpack', 'handbag', 'umbrella', 'skateboard', 'bicycle', 'car',
  'dog', 'cat', 'bird', 'person',
];
