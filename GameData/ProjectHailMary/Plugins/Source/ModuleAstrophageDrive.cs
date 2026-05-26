using System;
using System.Collections;
using UnityEngine;

namespace ProjectHailMary
{
    /// <summary>
    /// Companion module for the Astrophage photon drive.
    /// Sits alongside ModuleEnginesFX and adds:
    ///   • Breeding Mode — slowly generates Astrophage in nearby tanks when
    ///     the engine is off and the vessel is in adequate stellar flux.
    ///   • An orange/gold point light that scales with throttle level.
    ///   • GUI readouts for drive status, fuel flow, and solar flux.
    /// </summary>
    public class ModuleAstrophageDrive : PartModule
    {
        // ── Config fields ──────────────────────────────────────────────────

        [KSPField]
        public float maxThrust = 1800f;

        [KSPField]
        public float astrophageConsumptionRate = 0.00012f;  // u/s at full thrust (display only)

        [KSPField]
        public float breedingRate = 0.04f;      // u/s added to tanks when breeding

        [KSPField]
        public float breedingMinFlux = 200f;    // W/m² floor — organisms won't breed in the dark

        // ── Persistent GUI state ───────────────────────────────────────────

        [KSPField(isPersistant = true, guiActive = true, guiActiveEditor = true,
                  guiName = "Breeding Mode")]
        [UI_Toggle(disabledText = "Off", enabledText = "On")]
        public bool breedingModeEnabled = false;

        [KSPField(guiActive = true, guiName = "Drive Status")]
        public string driveStatus = "Offline";

        [KSPField(guiActive = true, guiName = "Astrophage Flow", guiFormat = "F4", guiUnits = " u/s")]
        public float currentConsumption = 0f;

        [KSPField(guiActive = true, guiName = "Solar Flux", guiFormat = "F1", guiUnits = " W/m²")]
        public float currentSolarFlux = 0f;

        // ── Private state ──────────────────────────────────────────────────

        private ModuleEnginesFX _stockEngine;
        private Light           _engineLight;
        private float           _throttle = 0f;

        // ── Lifecycle ──────────────────────────────────────────────────────

        public override void OnStart(StartState state)
        {
            base.OnStart(state);
            _stockEngine = part.FindModuleImplementing<ModuleEnginesFX>();
            if (state != StartState.Editor) SetupEngineLight();
        }

        private void SetupEngineLight()
        {
            var go = new GameObject("AstrophageDriveLight");
            go.transform.SetParent(part.transform, false);
            go.transform.localPosition = new Vector3(0f, -2.5f, 0f);

            _engineLight           = go.AddComponent<Light>();
            _engineLight.type      = LightType.Point;
            _engineLight.color     = new Color(1f, 0.6f, 0.15f, 1f);
            _engineLight.range     = 0f;
            _engineLight.intensity = 0f;
            _engineLight.enabled   = true;
        }

        // ── Update ─────────────────────────────────────────────────────────

        public void FixedUpdate()
        {
            if (!HighLogic.LoadedSceneIsFlight) return;

            UpdateSolarFlux();
            UpdateEngineState();
            UpdateBreeding();
            UpdateLight();
        }

        private void UpdateSolarFlux()
        {
            double flux = 0;
            foreach (var body in FlightGlobals.Bodies)
            {
                if (body.GetTemperature(0) < 3000) continue;
                double dist = Vector3d.Distance(vessel.GetWorldPos3D(), body.position);
                double lum  = body.Mass * 3.828e26 / 1.989e30;   // solar luminosities
                flux += lum * 3.828e26 / (4 * Math.PI * dist * dist);
            }
            currentSolarFlux = (float)flux;
        }

        private void UpdateEngineState()
        {
            if (_stockEngine == null) return;

            bool running = _stockEngine.isOperational && _stockEngine.currentThrottle > 0f;
            _throttle    = running ? _stockEngine.currentThrottle : 0f;

            if (running)
            {
                currentConsumption = astrophageConsumptionRate * _throttle;
                driveStatus        = $"Active ({_throttle * 100f:F0}%)";
            }
            else
            {
                currentConsumption = 0f;
                driveStatus        = breedingModeEnabled ? "Breeding" : "Standby";
            }
        }

        private void UpdateBreeding()
        {
            if (!breedingModeEnabled || _throttle > 0f) return;
            if (currentSolarFlux < breedingMinFlux) return;

            double toAdd = breedingRate * TimeWarp.fixedDeltaTime;

            // Distribute to all tanks on the vessel that hold Astrophage
            foreach (Part p in vessel.parts)
            {
                if (toAdd <= 0.0) break;
                var res = p.Resources["Astrophage"];
                if (res == null) continue;
                double space = res.maxAmount - res.amount;
                if (space <= 0.0) continue;
                double add  = Math.Min(space, toAdd);
                res.amount += add;
                toAdd      -= add;
            }
        }

        private void UpdateLight()
        {
            if (_engineLight == null) return;

            _engineLight.intensity = Mathf.Lerp(_engineLight.intensity, _throttle * 6f,  0.1f);
            _engineLight.range     = Mathf.Lerp(_engineLight.range,     _throttle * 80f, 0.1f);

            // Low throttle = deep orange; high throttle = blue-white Cherenkov glow
            _engineLight.color = Color.Lerp(
                new Color(1f, 0.55f, 0.1f),
                new Color(0.7f, 0.85f, 1f),
                _throttle
            );
        }

        // ── KSP Events ─────────────────────────────────────────────────────

        [KSPEvent(guiActive = true, guiName = "Toggle Breeding Mode", guiActiveEditor = false)]
        public void ToggleBreeding()
        {
            breedingModeEnabled = !breedingModeEnabled;
            ScreenMessages.PostScreenMessage(
                breedingModeEnabled
                    ? "Astrophage Breeding Mode: ENABLED — organisms will multiply near stars."
                    : "Astrophage Breeding Mode: DISABLED.",
                4f, ScreenMessageStyle.UPPER_CENTER
            );
        }

        [KSPAction("Toggle Breeding Mode")]
        public void ToggleBreedingAction(KSPActionParam param) => ToggleBreeding();
    }
}
