import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/glasses_state.dart';
import '../state/library.dart';
import '../state/social.dart';
import '../widgets/paper.dart';
import 'book_screen.dart';
import 'friends_screen.dart';
import 'hunts_screen.dart';
import 'scrap_screen.dart';
import 'studio_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int tab = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<GlassesState>().start();
      // A different account may have been signed in before: never show its data, then load (with retries).
      context.read<Library>()..reset()..refreshAll().catchError((_) {});
      context.read<Social>()..reset()..refreshAll().catchError((_) {});
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      final g = context.read<GlassesState>();
      g.refreshStatus();
      g.drainOutbox();
      context.read<Social>().refreshInbox().catchError((_) {});
      final lib = context.read<Library>();
      if (lib.loadError != null) lib.refreshAll().catchError((_) {}); // coming back online
    }
  }

  @override
  Widget build(BuildContext context) {
    final unseen = context.select<Social, int>((s) => s.unseen);
    const pages = [ScrapScreen(), BookScreen(), StudioScreen(), HuntsScreen(), FriendsScreen()];
    return Scaffold(
      body: PaperBackground(child: SafeArea(bottom: false, child: IndexedStack(index: tab, children: pages))),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: [
          const NavigationDestination(icon: Icon(Icons.camera_rounded), label: 'Scrap'),
          const NavigationDestination(icon: Icon(Icons.auto_stories_rounded), label: 'Book'),
          const NavigationDestination(icon: Icon(Icons.view_in_ar_rounded), label: 'Studio'),
          const NavigationDestination(icon: Icon(Icons.travel_explore_rounded), label: 'Hunts'),
          NavigationDestination(icon: Badge(isLabelVisible: unseen > 0, label: Text('$unseen'), child: const Icon(Icons.people_alt_rounded)), label: 'Friends'),
        ],
      ),
    );
  }
}
