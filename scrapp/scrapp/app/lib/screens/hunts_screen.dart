import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../services/ar_bridge.dart';
import '../services/location.dart';
import '../state/glasses_state.dart';
import '../state/library.dart';
import '../state/social.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/paper.dart';

class HuntsScreen extends StatelessWidget {
  const HuntsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final social = context.watch<Social>();
    final mine = social.hunts.where((h) => h.isOwner).toList();
    final shared = social.hunts.where((h) => !h.isOwner).toList();
    return RefreshIndicator(
      onRefresh: social.refreshHunts,
      child: ListView(padding: const EdgeInsets.fromLTRB(18, 12, 18, 32), children: [
        Text('SCAVENGER HUNTS', style: ScrappType.display(34)),
        const SizedBox(height: 6),
        const Text('Turn the places you scrapbooked into a hunt for friends. They find your favorites in real life.', style: TextStyle(color: Palette.inkSoft)),
        const SizedBox(height: 14),
        ScrappButton(label: 'Create a hunt', icon: Icons.add_location_alt_rounded, expand: true,
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const HuntBuilderScreen()))),
        const SectionTitle('From friends'),
        if (shared.isEmpty) const EmptyNote(icon: Icons.mail_outline_rounded, title: 'No hunts yet', body: 'When a friend sends you a hunt it shows up here.'),
        ...shared.map((h) => _HuntCard(hunt: h)),
        const SectionTitle('Yours'),
        if (mine.isEmpty) const EmptyNote(icon: Icons.map_outlined, title: 'Make your first hunt', body: 'Pick stickers with a location tag; each becomes something to find.'),
        ...mine.map((h) => _HuntCard(hunt: h)),
      ]),
    );
  }
}

class _HuntCard extends StatelessWidget {
  const _HuntCard({required this.hunt});
  final Hunt hunt;

  @override
  Widget build(BuildContext context) {
    final places = hunt.items.map((i) => i.placeName).whereType<String>().toSet();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: PaperCard(
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => HuntPlayScreen(huntId: hunt.id))),
        child: Row(children: [
          SizedBox(
            width: 56,
            height: 56,
            child: Stack(fit: StackFit.expand, children: [
              CircularProgressIndicator(value: hunt.total == 0 ? 0 : hunt.foundCount / hunt.total, strokeWidth: 6, color: Palette.sageDeep, backgroundColor: Palette.paper),
              Center(child: Text('${hunt.foundCount}/${hunt.total}', style: const TextStyle(fontWeight: FontWeight.w900))),
            ]),
          ),
          const SizedBox(width: 14),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(hunt.title, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 18)),
            if (places.isNotEmpty) Text(places.join(' · '), maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Palette.inkSoft)),
          ])),
          const Icon(Icons.chevron_right_rounded),
        ]),
      ),
    );
  }
}

class HuntBuilderScreen extends StatefulWidget {
  const HuntBuilderScreen({super.key});
  @override
  State<HuntBuilderScreen> createState() => _HuntBuilderScreenState();
}

class _HuntBuilderScreenState extends State<HuntBuilderScreen> {
  final title = TextEditingController();
  final description = TextEditingController();
  final picked = <String, TextEditingController>{}; // stickerId -> hint
  bool busy = false;

  @override
  Widget build(BuildContext context) {
    final stickers = context.watch<Library>().stickers.where((s) => s.hasLocation).toList();
    final byPlace = <String, List<Sticker>>{};
    for (final s in stickers) {
      byPlace.putIfAbsent(s.placeName ?? 'Unnamed place', () => []).add(s);
    }
    return Scaffold(
      appBar: AppBar(title: const Text('NEW HUNT')),
      body: PaperBackground(
        child: ListView(padding: const EdgeInsets.all(18), children: [
          TextField(controller: title, decoration: const InputDecoration(labelText: 'Hunt name', hintText: 'My favorites at the Nelson-Atkins')),
          const SizedBox(height: 10),
          TextField(controller: description, decoration: const InputDecoration(labelText: 'Note for your friends (optional)'), maxLines: 2),
          const SectionTitle('Pick the finds'),
          if (stickers.isEmpty) const EmptyNote(icon: Icons.location_off_rounded, title: 'No located stickers', body: 'Hunts are built from stickers that have a place. Scrapbook with location on (and allow location for Scrapp), then come back.'),
          for (final e in byPlace.entries) ...[
            Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text(e.key, style: const TextStyle(fontWeight: FontWeight.w900))),
            for (final s in e.value)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: PaperCard(
                  padding: const EdgeInsets.all(8),
                  color: picked.containsKey(s.id) ? Palette.teal : Palette.card,
                  onTap: () => setState(() {
                    if (picked.remove(s.id) == null) picked[s.id] = TextEditingController();
                  }),
                  child: Row(children: [
                    StickerImage(url: s.imageUrl, size: 64),
                    const SizedBox(width: 10),
                    Expanded(
                      child: picked.containsKey(s.id)
                          ? TextField(controller: picked[s.id], decoration: const InputDecoration(labelText: 'Hint (optional)', hintText: 'Second floor, near the windows'))
                          : Text(s.title, style: const TextStyle(fontWeight: FontWeight.w700)),
                    ),
                    Icon(picked.containsKey(s.id) ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded),
                  ]),
                ),
              ),
          ],
          const SizedBox(height: 14),
          ScrappButton(
            label: 'Create hunt (${picked.length})',
            icon: Icons.flag_rounded,
            expand: true,
            busy: busy,
            onPressed: picked.isEmpty || title.text.trim().isEmpty
                ? null
                : () async {
                    setState(() => busy = true);
                    try {
                      final h = await context.read<Social>().createHunt(title.text.trim(), description.text.trim(), [
                        for (final e in picked.entries) {'sticker_id': e.key, if (e.value.text.trim().isNotEmpty) 'hint': e.value.text.trim()},
                      ]);
                      if (context.mounted) Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => HuntPlayScreen(huntId: h.id)));
                    } catch (e) {
                      if (context.mounted) toast(context, '$e');
                    } finally {
                      if (mounted) setState(() => busy = false);
                    }
                  },
          ),
        ]),
      ),
    );
  }
}

class HuntPlayScreen extends StatefulWidget {
  const HuntPlayScreen({super.key, required this.huntId});
  final String huntId;
  @override
  State<HuntPlayScreen> createState() => _HuntPlayScreenState();
}

class _HuntPlayScreenState extends State<HuntPlayScreen> {
  Position? here;
  String? loadError;
  List<HuntPlayer> players = [];

  @override
  void initState() {
    super.initState();
    LocationService.current().then((p) => mounted ? setState(() => here = p) : null);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Hunt? get hunt => context.read<Social>().hunts.where((h) => h.id == widget.huntId).firstOrNull;

  /// Always refresh on open (found state, completion), and fetch it if the list doesn't have it yet.
  Future<void> _load() async {
    final social = context.read<Social>();
    setState(() => loadError = null);
    try {
      final h = await social.fetchHunt(widget.huntId);
      if (h.isOwner) {
        final p = await social.huntPlayers(widget.huntId);
        if (mounted) setState(() => players = p);
      }
    } catch (e) {
      if (mounted && hunt == null) setState(() => loadError = '$e');
    }
  }

  Future<void> _delete(Hunt h) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete this hunt?'),
        content: const Text('It disappears for everyone you sent it to.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete', style: TextStyle(color: Palette.danger))),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final social = context.read<Social>();
    final glasses = context.read<GlassesState>();
    if (glasses.activeHunt?.id == h.id) await glasses.setActiveHunt(null);
    await social.deleteHunt(h.id);
    if (mounted) Navigator.pop(context);
  }

  Future<void> _findWithPhone(Hunt h) async {
    final remaining = h.items.where((i) => !i.found && i.targetUrl != null && i.sticker?.imageUrl != null).toList();
    if (remaining.isEmpty) return;
    final found = await ArBridge.open(
      title: h.title,
      instructions: 'Point your camera at one of the finds',
      items: [
        for (final i in remaining)
          ArItem(id: i.itemId, imageUrl: i.sticker!.imageUrl!, title: i.title, targetUrl: i.targetUrl, anchor: AnchorSpec(mode: 'image', animation: i.animation)),
      ],
    );
    if (!mounted) return;
    final social = context.read<Social>();
    for (final id in found) {
      await social.markFound(h.id, id);
    }
    if (found.isNotEmpty && mounted) toast(context, 'Checked off ${found.length}!');
  }

  Future<void> _share(Hunt h) async {
    final social = context.read<Social>();
    await social.refreshFriends();
    if (!mounted) return;
    if (social.friends.isEmpty) {
      toast(context, 'Add a friend first (Friends tab), then send them the hunt.');
      return;
    }
    final picked = <String>{};
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(
        backgroundColor: Palette.card,
        title: const Text('Send hunt to'),
        content: Wrap(spacing: 8, children: [
          for (final f in social.friends)
            FilterChip(label: Text(f.displayName), selected: picked.contains(f.id), onSelected: (v) => set(() => v ? picked.add(f.id) : picked.remove(f.id))),
        ]),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Send'))],
      )),
    );
    if (ok == true && picked.isNotEmpty) {
      await social.share(kind: 'hunt', itemId: h.id, to: picked.toList());
      if (mounted) toast(context, 'Hunt sent');
    }
  }

  @override
  Widget build(BuildContext context) {
    context.watch<Social>();
    final glasses = context.watch<GlassesState>();
    final h = hunt;
    if (h == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('HUNT')),
        body: Center(
          child: loadError == null
              ? const CircularProgressIndicator()
              : Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const Text('Couldn\'t load this hunt.', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
                    const SizedBox(height: 6),
                    Text(loadError!, textAlign: TextAlign.center, style: const TextStyle(color: Palette.inkSoft)),
                    const SizedBox(height: 14),
                    ScrappButton(label: 'Try again', icon: Icons.refresh_rounded, onPressed: _load),
                  ]),
                ),
        ),
      );
    }
    final active = glasses.activeHunt?.id == h.id;
    return Scaffold(
      appBar: AppBar(
        title: Text(h.title.toUpperCase(), overflow: TextOverflow.ellipsis),
        actions: [
          if (h.isOwner) IconButton(tooltip: 'Send to friends', icon: const Icon(Icons.send_rounded), onPressed: () => _share(h)),
          if (h.isOwner) IconButton(tooltip: 'Delete hunt', icon: const Icon(Icons.delete_outline_rounded, color: Palette.danger), onPressed: () => _delete(h)),
        ],
      ),
      body: PaperBackground(
        child: ListView(padding: const EdgeInsets.all(18), children: [
          if (h.description?.isNotEmpty == true) Text(h.description!, style: const TextStyle(fontSize: 16)),
          const SizedBox(height: 10),
          LinearProgressIndicator(value: h.total == 0 ? 0 : h.foundCount / h.total, minHeight: 12, borderRadius: BorderRadius.circular(8), color: Palette.sageDeep, backgroundColor: Palette.card),
          const SizedBox(height: 6),
          Text('${h.foundCount} of ${h.total} found', style: const TextStyle(fontWeight: FontWeight.w900)),
          if (h.completed) ...[
            const SizedBox(height: 12),
            PaperCard(
              color: Palette.sage,
              child: Row(children: [
                const Icon(Icons.emoji_events_rounded, size: 34),
                const SizedBox(width: 12),
                Expanded(child: Text('Hunt complete! You found all ${h.total}.', style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 17))),
              ]),
            ),
          ],
          const SizedBox(height: 14),
          ScrappButton(
            label: active ? 'Hunting with glasses' : 'Hunt with my glasses',
            icon: active ? Icons.check_rounded : Icons.visibility_rounded,
            expand: true,
            onPressed: active
                ? null
                : () async {
                    final started = await context.read<Social>().startHunt(h.id);
                    await glasses.setActiveHunt(started);
                    if (!glasses.armed) await glasses.arm();
                    if (context.mounted) toast(context, 'Say "scrapbook that" when you find one.');
                  },
          ),
          const SizedBox(height: 10),
          ScrappButton(label: 'Find with phone camera', icon: Icons.center_focus_strong_rounded, style: ScrappButtonStyle.quiet, expand: true, onPressed: () => _findWithPhone(h)),
          const SectionTitle('Finds'),
          for (final i in h.items) _ItemCard(item: i, here: here),
          if (h.isOwner && players.isNotEmpty) ...[
            const SectionTitle('Players'),
            for (final p in players)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: PaperCard(
                  padding: const EdgeInsets.all(12),
                  child: Row(children: [
                    Icon(p.completed ? Icons.emoji_events_rounded : Icons.directions_walk_rounded),
                    const SizedBox(width: 10),
                    Expanded(child: Text(p.name, style: const TextStyle(fontWeight: FontWeight.w800))),
                    Text('${p.foundCount}/${p.total}', style: const TextStyle(fontWeight: FontWeight.w900)),
                  ]),
                ),
              ),
          ],
        ]),
      ),
    );
  }
}

class _ItemCard extends StatelessWidget {
  const _ItemCard({required this.item, this.here});
  final HuntItem item;
  final Position? here;

  @override
  Widget build(BuildContext context) {
    String? distance;
    if (here != null && item.lat != null) {
      final m = LocationService.distanceM(here!.latitude, here!.longitude, item.lat!, item.lng!);
      distance = m < 1000 ? '${m.round()} m away' : '${(m / 1000).toStringAsFixed(1)} km away';
    }
    final img = StickerImage(url: item.sticker?.imageUrl, size: 76);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: PaperCard(
        color: item.found ? Palette.sage : Palette.card,
        padding: const EdgeInsets.all(10),
        child: Row(children: [
          item.found
              ? img
              : ColorFiltered(colorFilter: const ColorFilter.matrix([0.33, 0.33, 0.33, 0, 0, 0.33, 0.33, 0.33, 0, 0, 0.33, 0.33, 0.33, 0, 0, 0, 0, 0, 0.6, 0]), child: img),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(item.title, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
            if (item.hint != null) Text(item.hint!, style: const TextStyle(color: Palette.inkSoft)),
            const SizedBox(height: 4),
            Wrap(spacing: 6, runSpacing: 4, children: [
              if (item.placeName != null) Pill(label: item.placeName!, icon: Icons.place_rounded, color: Palette.paper),
              if (distance != null && !item.found) Pill(label: distance, icon: Icons.near_me_rounded, color: Palette.paper),
            ]),
          ])),
          Icon(item.found ? Icons.check_circle_rounded : Icons.search_rounded, size: 28),
        ]),
      ),
    );
  }
}
