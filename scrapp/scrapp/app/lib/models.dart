double? _d(dynamic v) => v == null ? null : (v as num).toDouble();

class AppUser {
  AppUser({required this.id, required this.username, required this.displayName});
  final String id;
  final String username;
  final String displayName;
  factory AppUser.fromJson(Map<String, dynamic> j) =>
      AppUser(id: j['id'], username: j['username'], displayName: j['display_name'] ?? j['username']);
}

class Sticker {
  Sticker(this.j);
  final Map<String, dynamic> j;
  String get id => j['id'];
  String get ownerId => j['owner_id'];
  String get captureId => j['capture_id'];
  String? get imageUrl => j['image_url'];
  String get title => (j['title'] as String?)?.isNotEmpty == true ? j['title'] : 'Sticker';
  String? get placeName => j['place_name'];
  double? get lat => _d(j['lat']);
  double? get lng => _d(j['lng']);
  bool get isHero => j['is_hero'] == true;
  bool get starred => j['starred'] == true;
  DateTime? get capturedAt => j['captured_at'] == null ? null : DateTime.tryParse(j['captured_at']);
  bool get hasLocation => lat != null;
}

class Capture {
  Capture(this.j);
  final Map<String, dynamic> j;
  String get id => j['id'];
  String get status => j['status'] ?? 'processing';
  String? get originalUrl => j['original_url'];
  String? get placeName => j['place_name'];
  double? get lat => _d(j['lat']);
  double? get lng => _d(j['lng']);
  String get trigger => j['trigger'] ?? 'app';
  DateTime? get capturedAt => j['captured_at'] == null ? null : DateTime.tryParse(j['captured_at']);
  int get width => (j['width'] as num?)?.toInt() ?? 0;
  int get height => (j['height'] as num?)?.toInt() ?? 0;
  List<Sticker> get stickers => ((j['stickers'] as List?) ?? []).map((e) => Sticker(e)).toList();
  bool get processing => status == 'processing';
}

class Collage {
  Collage(this.j);
  final Map<String, dynamic> j;
  String get id => j['id'];
  String get title => j['title'] ?? 'Untitled collage';
  String? get thumbnailUrl => j['thumbnail_url'];
  Map<String, dynamic> get scene => Map<String, dynamic>.from(j['scene'] ?? const {});
}

class MeshJob {
  MeshJob(this.j);
  final Map<String, dynamic> j;
  String get id => j['id'];
  String get status => j['status'] ?? 'PENDING';
  String get stage => j['stage'] ?? 'preview';
  int get progress => (j['progress'] as num?)?.toInt() ?? 0;
  String? get prompt => j['prompt'];
  String? get stickerId => j['sticker_id'];
  String? get glbUrl => j['glb_url'];
  String? get thumbnailUrl => j['thumbnail_url'];
  String? get error => j['error'];
  bool get done => glbUrl != null;
  bool get failed => status == 'FAILED' || status == 'CANCELED';

  /// Text-to-3D is preview (0-50%) + refine (50-100%); image-to-3D is a single stage.
  double get overall => done
      ? 1
      : stage == 'preview'
          ? progress / 200
          : stage == 'refine'
              ? 0.5 + progress / 200
              : progress / 100;
}

/// How a shared sticker attaches to the real world when the receiver opens it in AR.
class AnchorSpec {
  AnchorSpec({this.mode = 'surface', this.objectClass, this.animation = 'wiggle', this.sizeM = 0.12, this.lat, this.lng, this.targetUrl});
  String mode; // none | surface | object | image | geo
  String? objectClass; // COCO label, e.g. "apple"
  String animation; // none | wiggle | bob | spin | pop
  double sizeM;
  double? lat;
  double? lng;
  String? targetUrl; // set by the server for mode=image (crop of the sender's original photo)

  factory AnchorSpec.fromJson(Map<String, dynamic>? j) => j == null
      ? AnchorSpec()
      : AnchorSpec(mode: j['mode'] ?? 'surface', objectClass: j['object_class'], animation: j['animation'] ?? 'wiggle',
          sizeM: _d(j['size_m']) ?? 0.12, lat: _d(j['lat']), lng: _d(j['lng']), targetUrl: j['target_url']);

  Map<String, dynamic> toJson() => {
        'mode': mode,
        'object_class': objectClass,
        'animation': animation,
        'size_m': sizeM,
        'lat': lat,
        'lng': lng,
      };
}

class InboxEntry {
  InboxEntry(this.j);
  final Map<String, dynamic> j;
  String get id => j['id'];
  String get kind => j['kind'];
  String? get message => j['message'];
  String get fromName => (j['from'] as Map?)?['display_name'] ?? 'A friend';
  Map<String, dynamic> get item => Map<String, dynamic>.from(j['item'] ?? const {});
  AnchorSpec get anchor => AnchorSpec.fromJson(j['anchor'] == null ? null : Map<String, dynamic>.from(j['anchor']));
  bool get seen => j['seen_at'] != null;
}

class HuntItem {
  HuntItem(this.j);
  final Map<String, dynamic> j;
  String get itemId => j['item_id'];
  String get title => j['title'] ?? 'Mystery find';
  String? get hint => j['hint'];
  String? get placeName => j['place_name'];
  double? get lat => _d(j['lat']);
  double? get lng => _d(j['lng']);
  double get radiusM => _d(j['radius_m']) ?? 150;
  bool get found => j['found'] == true;
  String? get targetUrl => j['target_url'];
  String get animation => j['animation'] ?? 'pop';
  Sticker? get sticker => j['sticker'] == null ? null : Sticker(Map<String, dynamic>.from(j['sticker']));
}

class Hunt {
  Hunt(this.j);
  final Map<String, dynamic> j;
  String get id => j['id'];
  String get title => j['title'] ?? 'Hunt';
  String? get description => j['description'];
  List<HuntItem> get items => ((j['items'] as List?) ?? []).map((e) => HuntItem(Map<String, dynamic>.from(e))).toList();
  int get foundCount => (j['found_count'] as num?)?.toInt() ?? 0;
  int get total => (j['total'] as num?)?.toInt() ?? items.length;
  bool get isOwner => j['is_owner'] == true;
  bool get started => j['started'] == true;
  bool get completed => j['completed'] == true;
  DateTime? get completedAt => j['completed_at'] == null ? null : DateTime.tryParse(j['completed_at']);
}

/// One player's progress in a hunt (owner view).
class HuntPlayer {
  HuntPlayer(this.j);
  final Map<String, dynamic> j;
  String get name => (j['user'] as Map?)?['display_name'] ?? (j['user'] as Map?)?['username'] ?? 'Someone';
  int get foundCount => (j['found_count'] as num?)?.toInt() ?? 0;
  int get total => (j['total'] as num?)?.toInt() ?? 0;
  bool get completed => j['completed_at'] != null;
}
