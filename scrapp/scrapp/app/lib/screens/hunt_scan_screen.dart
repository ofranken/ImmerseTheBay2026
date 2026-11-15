import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../services/location.dart';
import '../state/social.dart';
import '../theme/palette.dart';
import '../widgets/paper.dart';

/// Live phone-camera hunting. Shows the picture of the find you are after, scans a frame every few seconds (and on
/// "Scan now"), and says plainly what happened: scanning / close / matched / error. Nothing here fails silently.
class HuntScanScreen extends StatefulWidget {
  const HuntScanScreen({super.key, required this.huntId});
  final String huntId;
  @override
  State<HuntScanScreen> createState() => _HuntScanScreenState();
}

enum ScanPhase { starting, scanning, close, matched, none, error, noCamera }

class _HuntScanScreenState extends State<HuntScanScreen> with WidgetsBindingObserver {
  CameraController? cam;
  ScanPhase phase = ScanPhase.starting;
  String message = 'Starting the camera…';
  bool busy = false, auto = true;
  Timer? timer;
  Position? here;
  int scans = 0;
  String? lastFound;

  Hunt? get hunt => context.read<Social>().hunts.where((h) => h.id == widget.huntId).firstOrNull;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    LocationService.current().then((p) => here = p);
    _startCamera();
  }

  Future<void> _startCamera() async {
    try {
      final cams = await availableCameras();
      if (cams.isEmpty) throw 'No camera found';
      final back = cams.firstWhere((c) => c.lensDirection == CameraLensDirection.back, orElse: () => cams.first);
      final c = CameraController(back, ResolutionPreset.high, enableAudio: false);
      await c.initialize();
      if (!mounted) return c.dispose();
      setState(() {
        cam = c;
        phase = ScanPhase.scanning;
        message = 'Point at a find, fill the frame, hold steady.';
      });
      timer = Timer.periodic(const Duration(seconds: 3), (_) => auto ? scan() : null);
    } catch (e) {
      if (mounted) setState(() { phase = ScanPhase.noCamera; message = 'Camera unavailable ($e). Allow camera access in Settings, then reopen.'; });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    if (s == AppLifecycleState.inactive) auto = false;
    if (s == AppLifecycleState.resumed) auto = true;
  }

  Future<void> scan() async {
    final c = cam;
    if (busy || c == null || !c.value.isInitialized || !mounted) return;
    setState(() { busy = true; if (phase != ScanPhase.matched) message = 'Scanning…'; });
    try {
      final shot = await c.takePicture();
      here ??= await LocationService.current();
      if (!mounted) return;
      final r = await context.read<Social>().scanHunt(widget.huntId, shot.path, lat: here?.latitude, lng: here?.longitude, accuracy: here?.accuracy);
      scans++;
      if (!mounted) return;
      setState(() {
        message = r.message;
        phase = switch (r.status) { 'matched' => ScanPhase.matched, 'close' => ScanPhase.close, _ => ScanPhase.none };
        if (r.matched) lastFound = r.foundTitle;
      });
    } catch (e) {
      if (mounted) setState(() { phase = ScanPhase.error; message = 'Scan failed: $e. Check your connection, then tap Scan now.'; });
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    cam?.dispose();
    super.dispose();
  }

  Color get tint => switch (phase) {
        ScanPhase.matched => Palette.sage,
        ScanPhase.close => const Color(0xFFFFE08A),
        ScanPhase.error || ScanPhase.noCamera => const Color(0xFFF5B7B1),
        _ => Palette.card,
      };

  @override
  Widget build(BuildContext context) {
    context.watch<Social>();
    final h = hunt;
    final remaining = h?.items.where((i) => !i.found).toList() ?? [];
    final done = h != null && remaining.isEmpty;
    return Scaffold(
      appBar: AppBar(title: Text((h?.title ?? 'Hunt').toUpperCase(), overflow: TextOverflow.ellipsis)),
      body: Column(children: [
        Expanded(
          child: Stack(fit: StackFit.expand, children: [
            if (cam != null && cam!.value.isInitialized) ClipRect(child: FittedBox(fit: BoxFit.cover, child: SizedBox(width: cam!.value.previewSize!.height, height: cam!.value.previewSize!.width, child: CameraPreview(cam!)))) else const ColoredBox(color: Colors.black),
            IgnorePointer(child: Center(child: FractionallySizedBox(widthFactor: 0.82, heightFactor: 0.62, child: DecoratedBox(decoration: BoxDecoration(border: Border.all(color: phase == ScanPhase.matched ? Palette.sageDeep : Colors.white, width: 3), borderRadius: BorderRadius.circular(18)))))),
            Positioned(left: 12, right: 12, top: 12, child: PaperCard(color: tint, padding: const EdgeInsets.all(12), child: Row(children: [
              if (busy) const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.5)) else Icon(switch (phase) { ScanPhase.matched => Icons.check_circle_rounded, ScanPhase.close => Icons.adjust_rounded, ScanPhase.error || ScanPhase.noCamera => Icons.error_outline_rounded, _ => Icons.center_focus_strong_rounded }),
              const SizedBox(width: 10),
              Expanded(child: Text(message, key: const Key('scanMessage'), style: const TextStyle(fontWeight: FontWeight.w800))),
            ]))),
          ]),
        ),
        Container(
          color: Palette.paper,
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 14),
          child: SafeArea(top: false, child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (done) const Text('Hunt complete! You found everything.', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16))
            else ...[
              Text('Find these (${h?.foundCount ?? 0} of ${h?.total ?? 0} done). Hold the real thing in view:', style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              SizedBox(height: 84, child: ListView(scrollDirection: Axis.horizontal, children: [
                for (final i in remaining) Padding(padding: const EdgeInsets.only(right: 10), child: Column(children: [
                  ClipRRect(borderRadius: BorderRadius.circular(10), child: StickerImage(url: i.sticker?.imageUrl ?? i.targetUrl, size: 62)),
                ])),
              ])),
            ],
            const SizedBox(height: 8),
            Row(children: [
              Expanded(child: ScrappButton(label: busy ? 'Scanning…' : 'Scan now', icon: Icons.center_focus_strong_rounded, expand: true, onPressed: busy || cam == null ? null : scan)),
              const SizedBox(width: 10),
              Column(children: [
                Switch(value: auto, onChanged: (v) => setState(() => auto = v)),
                const Text('Auto', style: TextStyle(fontSize: 11)),
              ]),
            ]),
          ])),
        ),
      ]),
    );
  }
}
