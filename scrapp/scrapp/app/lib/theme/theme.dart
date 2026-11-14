import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'palette.dart';

class ScrappType {
  /// Condensed display face for big section titles only (>= 24 sp).
  static TextStyle display(double size) =>
      GoogleFonts.anton(fontSize: size, color: Palette.ink, letterSpacing: 0.6, height: 1.05);

  /// Script used only for the "Scrapp" wordmark.
  static TextStyle wordmark(double size) => GoogleFonts.yellowtail(fontSize: size, color: Palette.ink);
}

ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: Palette.teal,
      primary: Palette.tealDeep,
      onPrimary: Colors.white,
      secondary: Palette.sage,
      surface: Palette.card,
      onSurface: Palette.ink,
      error: Palette.danger,
    ),
    scaffoldBackgroundColor: Palette.paper,
  );
  final text = GoogleFonts.nunitoTextTheme(base.textTheme).apply(bodyColor: Palette.ink, displayColor: Palette.ink);
  return base.copyWith(
    textTheme: text.copyWith(
      bodyLarge: text.bodyLarge?.copyWith(fontSize: 17, height: 1.4),
      bodyMedium: text.bodyMedium?.copyWith(fontSize: 15, height: 1.4),
      labelLarge: text.labelLarge?.copyWith(fontWeight: FontWeight.w800, fontSize: 16),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: Colors.transparent,
      elevation: 0,
      foregroundColor: Palette.ink,
      centerTitle: false,
      titleTextStyle: ScrappType.display(26),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Palette.card,
      indicatorColor: Palette.teal,
      height: 72,
      labelTextStyle: WidgetStatePropertyAll(GoogleFonts.nunito(fontWeight: FontWeight.w800, fontSize: 12, color: Palette.ink)),
      iconTheme: const WidgetStatePropertyAll(IconThemeData(color: Palette.ink)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Palette.card,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: Palette.inkSoft, width: 1.2)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: Palette.inkSoft.withValues(alpha: 0.4), width: 1.2)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: Palette.tealDeep, width: 2)),
      labelStyle: const TextStyle(color: Palette.inkSoft),
    ),
    snackBarTheme: const SnackBarThemeData(backgroundColor: Palette.ink, contentTextStyle: TextStyle(color: Palette.card, fontWeight: FontWeight.w700)),
    sliderTheme: const SliderThemeData(activeTrackColor: Palette.tealDeep, thumbColor: Palette.ink, inactiveTrackColor: Palette.teal),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: Palette.card,
      selectedColor: Palette.teal,
      side: BorderSide(color: Palette.inkSoft.withValues(alpha: 0.35)),
      labelStyle: GoogleFonts.nunito(fontWeight: FontWeight.w700, color: Palette.ink),
    ),
  );
}
