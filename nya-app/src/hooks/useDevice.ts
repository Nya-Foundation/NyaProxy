import { computed, onMounted, ref } from 'vue';
import { useEventListener } from './useEventListener';

/**
 * Device detection composable
 * Provides comprehensive mobile device detection including user agent and responsive breakpoints
 */
export function useDevice() {
  // Reactive states
  const isMobile = ref(false);
  const isTablet = ref(false);
  const screenWidth = ref(0);
  const screenHeight = ref(0);

  // Breakpoints configuration
  const breakpoints = {
    mobile: 768,
    tablet: 1024,
    desktop: 1200
  } as const;

  // User agent based device detection
  const detectUserAgent = (): {
    mobile: boolean;
    tablet: boolean;
    ios: boolean;
    android: boolean;
  } => {
    if (typeof window === 'undefined') {
      return { mobile: false, tablet: false, ios: false, android: false };
    }

    const userAgent = navigator.userAgent.toLowerCase();

    // Mobile device patterns
    const mobilePatterns = [
      /android.*mobile/,
      /iphone/,
      /ipod/,
      /blackberry/,
      /windows phone/,
      /mobile/
    ];

    // Tablet device patterns
    const tabletPatterns = [/ipad/, /android(?!.*mobile)/, /tablet/, /kindle/, /playbook/, /silk/];

    const isMobileUA = mobilePatterns.some(pattern => pattern.test(userAgent));
    const isTabletUA = tabletPatterns.some(pattern => pattern.test(userAgent));
    const isIOS = /iphone|ipad|ipod/.test(userAgent);
    const isAndroid = /android/.test(userAgent);

    return {
      mobile: isMobileUA,
      tablet: isTabletUA,
      ios: isIOS,
      android: isAndroid
    };
  };

  // Cache user agent info
  const userAgentInfo = detectUserAgent();

  // Screen size based detection
  const updateScreenSize = () => {
    if (typeof window === 'undefined') return;

    screenWidth.value = window.innerWidth;
    screenHeight.value = window.innerHeight;

    // Combine user agent and screen size detection
    // Mobile: UA detection OR screen width < mobile breakpoint
    isMobile.value = userAgentInfo.mobile || screenWidth.value < breakpoints.mobile;

    // Tablet: UA detection OR screen width between mobile and desktop (but not mobile UA)
    isTablet.value =
      userAgentInfo.tablet ||
      (!userAgentInfo.mobile &&
        screenWidth.value >= breakpoints.mobile &&
        screenWidth.value < breakpoints.desktop);
  };

  // Touch capability detection
  const isTouchDevice = ref(false);
  const detectTouchCapability = (): boolean => {
    if (typeof window === 'undefined') return false;

    return (
      'ontouchstart' in window ||
      navigator.maxTouchPoints > 0 ||
      (navigator as any).msMaxTouchPoints > 0
    );
  };

  // Device orientation - computed property for better reactivity
  const orientation = computed<'portrait' | 'landscape'>(() => {
    if (screenHeight.value === 0 || screenWidth.value === 0) return 'portrait';
    return screenHeight.value > screenWidth.value ? 'portrait' : 'landscape';
  });

  // Computed device type for better reactivity
  const deviceType = computed<'mobile' | 'tablet' | 'desktop'>(() => {
    if (isMobile.value) return 'mobile';
    if (isTablet.value) return 'tablet';
    return 'desktop';
  });

  // Unified resize handler
  const handleResize = () => {
    updateScreenSize();
  };

  // Initialize and setup event listeners using useEventListener
  const initialize = () => {
    updateScreenSize();
    isTouchDevice.value = detectTouchCapability();
  };

  // Setup event listeners using useEventListener hook
  const { removeEvent: removeResizeListener } = useEventListener({
    el: window,
    name: 'resize',
    listener: handleResize,
    wait: 100,
    isDebounce: true
  });

  const { removeEvent: removeOrientationListener } = useEventListener({
    el: window,
    name: 'orientationchange',
    listener: handleResize,
    wait: 150,
    isDebounce: true
  });

  // Initialize on mount
  onMounted(() => {
    initialize();
  });

  // Utility functions
  const isScreenSize = (size: keyof typeof breakpoints): boolean => {
    const width = screenWidth.value;
    switch (size) {
      case 'mobile':
        return width < breakpoints.mobile;
      case 'tablet':
        return width >= breakpoints.mobile && width < breakpoints.desktop;
      case 'desktop':
        return width >= breakpoints.desktop;
      default:
        return false;
    }
  };

  const isAtLeast = (size: keyof typeof breakpoints): boolean => {
    return screenWidth.value >= breakpoints[size];
  };

  const isAtMost = (size: keyof typeof breakpoints): boolean => {
    return screenWidth.value <= breakpoints[size];
  };

  // Manual cleanup function (optional, useEventListener handles auto cleanup)
  const cleanup = () => {
    removeResizeListener();
    removeOrientationListener();
  };

  return {
    // Reactive states
    isMobile,
    isTablet,
    isTouchDevice,
    screenWidth,
    screenHeight,
    orientation,
    deviceType,

    // User agent detection results
    isIOS: userAgentInfo.ios,
    isAndroid: userAgentInfo.android,

    // Utility functions
    isScreenSize,
    isAtLeast,
    isAtMost,

    // Breakpoints for external use
    breakpoints,

    // Manual refresh and cleanup functions
    refresh: initialize,
    cleanup
  };
}

export default useDevice;
