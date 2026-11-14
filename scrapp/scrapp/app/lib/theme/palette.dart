import 'package:flutter/material.dart';

/// Combined palette: "vintage" (#694A47 / #96C1C5 / #FFF0DE) + "chocolate/sage/cream"
/// (#5C3A26 / #A3B18A / #F1E7D3). Text always uses the two browns for contrast.
class Palette {
  static const ink = Color(0xFF5C3A26); // chocolate brown: primary text, icons
  static const inkSoft = Color(0xFF694A47); // vintage brown: secondary text, borders
  static const paper = Color(0xFFF1E7D3); // warm cream: page background
  static const card = Color(0xFFFFF0DE); // vintage cream: cards, sheets
  static const teal = Color(0xFF96C1C5); // dusty teal: primary actions, AR, sharing
  static const sage = Color(0xFFA3B18A); // soft sage: 3D/mesh, success, nature
  static const sageDeep = Color(0xFF6F7F55);
  static const tealDeep = Color(0xFF4E8288);
  static const danger = Color(0xFFB5483D);
  static const inside = Color(0xFF7E8F62); // save-zone green
  static const outside = Color(0xFFC2564B); // exclude-zone red
}
