using System;
using UnityEngine;
using KSP.UI.Screens;

namespace ProjectHailMary
{
    /// <summary>
    /// Tracks the global Astrophage Crisis timeline.
    /// As in-game time passes, Kerbol gradually dims. Crisis messages appear
    /// in the KSC news feed. Dimming stops if the Hail Mary launches.
    /// </summary>
    [KSPScenario(
        ScenarioCreationOptions.AddToAllGames,
        new[] { GameScenes.SPACECENTER, GameScenes.FLIGHT, GameScenes.TRACKSTATION }
    )]
    public class AstrophageScenario : ScenarioModule
    {
        // ── Persistent state ───────────────────────────────────────────────

        [KSPField(isPersistant = true)]
        public double crisisStartTime = -1.0;

        [KSPField(isPersistant = true)]
        public float sunDimmingFraction = 0f;

        [KSPField(isPersistant = true)]
        public bool crisisActive = false;

        [KSPField(isPersistant = true)]
        public bool missionLaunched = false;

        [KSPField(isPersistant = true)]
        public int lastMessageIndex = -1;

        // ── Constants ──────────────────────────────────────────────────────

        private const float  MaxDimming           = 0.25f;
        private const double CrisisDurationSeconds = 7 * 426.0 * 6 * 3600.0;  // 7 KSP years

        private static readonly string[] CrisisMessages =
        {
            "[CRISIS Y1] Astronomers confirm the Petrova Line — a band of organisms consuming stellar radiation between Kerbin and Kerbol. Scientists call them 'Astrophage'. Solar output has dropped 0.3%. The Agency is monitoring.",
            "[CRISIS Y2] Solar output now down 0.6%. Astrophage reproduction models suggest exponential growth. Average global temperatures have dropped 0.15°C. The Agency declares a Tier 1 emergency.",
            "[CRISIS Y3] Crop yields falling across Kerbin's northern hemisphere. Astrophage concentration in the Petrova Line has doubled. Scientists scramble to understand the organism's biology. Every nation contributes to Project Hail Mary.",
            "[CRISIS Y4] The Hail Mary spacecraft is under construction. A pilot must be found — or grown. The mission profile calls for a one-way trip to Tau Ceti, where the infestation is far worse yet somehow controlled. There may be an answer there.",
            "[CRISIS Y5] Launch window for the Hail Mary opens in 180 days. The crew will be placed in medically-induced coma for the 13-year transit. One will survive to complete the mission. If the answer exists, they will find it.",
            "[CRISIS Y6] The Hail Mary has launched. Kerbol's output is down 1.4%. Winters grow longer. Humanity's fate travels alone toward another star at 1.5% the speed of light. Godspeed, Hail Mary.",
            "[CRISIS Y7+] Kerbol output continues to decline. The Hail Mary is beyond communication range. All we can do is wait, and hope that whoever wakes up out there remembers who they are and why they came."
        };

        // ── Baseline light intensity (stored on first dimming update) ──────
        private float _baselineSunIntensity = -1f;

        // ── Lifecycle ──────────────────────────────────────────────────────

        public override void OnAwake()
        {
            base.OnAwake();
            GameEvents.onVesselSituationChange.Add(OnVesselSituationChange);
        }

        private void OnDestroy()
        {
            GameEvents.onVesselSituationChange.Remove(OnVesselSituationChange);
        }

        public override void OnLoad(ConfigNode node) { }
        public override void OnSave(ConfigNode node) { }

        public void Update()
        {
            if (!HighLogic.LoadedSceneIsGame) return;
            if (!crisisActive) TryStartCrisis();
            if (crisisActive)  UpdateDimming();
            DeliverMessages();
        }

        // ── Crisis logic ───────────────────────────────────────────────────

        private void TryStartCrisis()
        {
            double oneYear = 426.0 * 6 * 3600.0;
            if (Planetarium.GetUniversalTime() > oneYear)
            {
                crisisActive    = true;
                crisisStartTime = Planetarium.GetUniversalTime();
                PostMessage("INCOMING TRANSMISSION — KERBAL ASTRONOMICAL SURVEY", 8f);
            }
        }

        private void UpdateDimming()
        {
            double elapsed  = Planetarium.GetUniversalTime() - crisisStartTime;
            float  progress = (float)Math.Min(elapsed / CrisisDurationSeconds, 1.0);
            float  sigmoid  = 1f / (1f + Mathf.Exp(-8f * (progress - 0.5f)));
            sunDimmingFraction = missionLaunched ? 0f : sigmoid * MaxDimming;

            ApplySolarDimming();
        }

        private void ApplySolarDimming()
        {
            if (Sun.Instance == null) return;
            var sunLight = Sun.Instance.GetComponent<Light>();
            if (sunLight == null) return;

            // Capture baseline once so we always scale relative to the stock value
            if (_baselineSunIntensity < 0f)
                _baselineSunIntensity = sunLight.intensity > 0.01f ? sunLight.intensity : 0.9f;

            sunLight.intensity = _baselineSunIntensity * (1f - sunDimmingFraction);
        }

        private void DeliverMessages()
        {
            if (!crisisActive) return;
            double elapsed   = Planetarium.GetUniversalTime() - crisisStartTime;
            double oneYear   = 426.0 * 6 * 3600.0;
            int    yearIndex = (int)(elapsed / oneYear);
            if (yearIndex > lastMessageIndex && yearIndex < CrisisMessages.Length)
            {
                lastMessageIndex = yearIndex;
                PostMessage(CrisisMessages[yearIndex], 12f);
            }
        }

        // ── Event handlers ─────────────────────────────────────────────────

        private void OnVesselSituationChange(GameEvents.HostedFromToAction<Vessel, Vessel.Situations> data)
        {
            if (!crisisActive || missionLaunched) return;
            if (data.to != Vessel.Situations.ESCAPING) return;

            var vessel        = data.host;
            bool hasDrive     = vessel.FindPartModuleImplementing<ModuleAstrophageDrive>() != null;
            bool hasPod       = vessel.Parts.Exists(p => p.partInfo?.name == "hailmary_pod");

            if (hasDrive && hasPod)
            {
                missionLaunched = true;
                PostMessage(
                    "The Hail Mary has escaped Kerbin's gravitational influence. " +
                    "Tau Ceti drive engaged. Crew entering coma in T+72 hours. Godspeed, Hail Mary.",
                    15f
                );
            }
        }

        private static void PostMessage(string msg, float duration)
        {
            ScreenMessages.PostScreenMessage(
                "<color=#FFA500><b>" + msg + "</b></color>",
                duration, ScreenMessageStyle.UPPER_CENTER
            );
        }
    }
}
