import 'package:flutter/material.dart';

/// A choice in the collage Background picker. `json` is what goes into scene.background (null = the default paper).
class BackgroundPreset {
  const BackgroundPreset(this.label, this.json, {this.swatch, this.gradient});
  final String label;
  final Map<String, dynamic>? json;
  final Color? swatch;
  final List<Color>? gradient;
}

Color _hex(String h) => Color(0xFF000000 | int.parse(h.substring(1), radix: 16));

BackgroundPreset _color(String label, String hex) => BackgroundPreset(label, {'type': 'color', 'value': hex}, swatch: _hex(hex));
BackgroundPreset _gradient(String label, List<String> hex, [double angle = 180]) =>
    BackgroundPreset(label, {'type': 'gradient', 'colors': hex, 'angle': angle}, gradient: [for (final h in hex) _hex(h)]);

/// Everything the picker offers, besides "a photo of yours".
final List<BackgroundPreset> backgroundPresets = [
  const BackgroundPreset('Default', null, swatch: Color(0xFFF1E7D3)),
  const BackgroundPreset('Paper', {'type': 'paper'}, swatch: Color(0xFFF1E7D3)),
  _color('Cream', '#FFF6E5'),
  _color('Ink', '#2B2420'),
  _color('Sky blue', '#8EC5E6'),
  _color('Sage', '#B8C7A1'),
  _color('Blush', '#F4C6C0'),
  _gradient('Sky', ['#8EC5E6', '#E8F4FB']),
  _gradient('Sunset', ['#FFB36B', '#F36B8B', '#5B4B9A']),
  _gradient('Mint', ['#D9F2E6', '#7FC8A9']),
  _gradient('Night', ['#1B1F3B', '#3E3C7A', '#7B5EA7']),
  _gradient('Dawn', ['#FDE2C8', '#F7B6A5'], 135),
];

final _hexColor = RegExp(r'^#[0-9a-fA-F]{6}$');

/// The same rules the server enforces on save, so a bad value is caught before it is sent.
bool isValidBackground(Map<String, dynamic>? bg) {
  if (bg == null) return true;
  switch (bg['type']) {
    case 'paper':
      return true;
    case 'color':
      return bg['value'] is String && _hexColor.hasMatch(bg['value']);
    case 'gradient':
      final c = bg['colors'];
      final a = bg['angle'];
      return c is List && c.length >= 2 && c.length <= 4 && c.every((x) => x is String && _hexColor.hasMatch(x)) && (a == null || (a is num && a >= 0 && a <= 360));
    case 'photo':
      return bg['ref_id'] is String && (bg['ref_id'] as String).isNotEmpty;
  }
  return false;
}

/// scene.background for a photo backdrop: one of the user's captures. `url` is for live display only; the server
/// re-signs it on every load and never stores it.
Map<String, dynamic> photoBackground(String captureId, String? url) => {'type': 'photo', 'ref_id': captureId, if (url != null) 'url': url};

/// True when two backgrounds are the same choice (ignores the live-only photo url).
bool sameBackground(Map<String, dynamic>? a, Map<String, dynamic>? b) {
  if (a == null || b == null) return a == null && b == null;
  if (a['type'] != b['type']) return false;
  switch (a['type']) {
    case 'color':
      return a['value'] == b['value'];
    case 'gradient':
      return a['colors'].toString() == b['colors'].toString();
    case 'photo':
      return a['ref_id'] == b['ref_id'];
  }
  return true;
}
