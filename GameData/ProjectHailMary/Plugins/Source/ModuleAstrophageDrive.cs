using System;
using System.Collections;
using UnityEngine;

namespace ProjectHailMary
{
    /// <summary>
    /// Custom engine module for the Astrophage photon drive.
    ///
    /// Key behaviours beyond a stock engine:
    ///   • Astrophage consumption scales with thrust level (organisms are
    ///     "pushed" harder when more thrust is demanded).
    ///   • An orange/gold engine glow brightens with thrust level.
    ///   • A "Breeding Mode" can slowly generate Astrophage when the engine
    ///     is off and the vessel is near a star, simulating organisms feeding.
    ///   • Thrust and ISP are constant in vacuum (photon drive — no exhaust
    ///     velocity change with altitude, except near 0 in thick atmosphere
    ///     because the plume is disrupted).
    /// </summary>
    public class ModuleAstrophageDrive : PartModule
    {
        // ── Config fields ──────────────────────────────────────────────────

        [KSPField]
        public float maxThrust = 450f;          // kN

        [KSPField]
        public float minThrust = 0f;

        [KSPField]
        public string thrustVectorTransformName = "thrustTransform";

        [KSPField]
        public float astrophageConsumptionRate = 0.00012f;  // units/s at full thrust

        [KSPField]
        public float breedingRate = 0.002f;     // units/s when breeding near star

        [KSPField]
        public float breedingMinFlux = 200f;    // W/m² minimum solar flux to breed

        // ── Persistent state ───────────────────────────────────────────────

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
        private Light _engineLight;
        private bool _engineRunning = false;
        private float _throttle = 0f;

        // ── Lifecycle ──────────────────────────────────────────────────────

        public override void OnStart(StartState state)
        {
            base.OnStart(state);

            _stockEngine = part.FindModuleImplementing<ModuleEnginesFX>();

            if (state == StartState.Editor) return;

            SetupEngineLight();
        }

        private void SetupEngineLight()
        {
            var lightObj = new GameObject("AstrophageDriveLight");
            lightObj.transform.SetParent(part.transform, false);
            lightObj.transform.localPosition = new Vector3(0, -2.5f, 0);

            _engineLight          = lightObj.AddComponent<Light>();
            _engineLight.type     = LightType.Point;
            _engineLight.color    = new Color(1f, 0.6f, 0.15f, 1f);
            _engineLight.range    = 0f;
            _engineLight.intensity = 0f;
            _engineLight.enabled  = true;
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
            // KSP exposes solar flux through PhysicsGlobals after 1.2
            double flux = 0;
            foreach (var star in FlightGlobals.Bodies)
            {
                if (star.GetTemperature(0) > 3000)  // rough star check
                {
                    double dist = Vector3d.Distance(
                        vessel.GetWorldPos3D(),
                        star.position
                    );
                    // Inverse-square law; star.radiusAtmosphere used as proxy luminosity
                    double lum = star.Mass * 3.828e26 / 1.989e30; // solar luminosities
                    flux += lum * 3.828e26 / (4 * Math.PI * dist * dist);
                }
            }
            currentSolarFlux = (float)flux;
        }

        private void UpdateEngineState()
        {
            if (_stockEngine == null) return;

            _engineRunning = _stockEngine.isOperational && _stockEngine.currentThrottle > 0f;
            _throttle      = _engineRunning ? _stockEngine.currentThrottle : 0f;

            if (_engineRunning)
            {
                currentConsumption = astrophageConsumptionRate * _throttle;
                driveStatus = $"Active ({_throttle * 100f:F0}%)";
            }
            else
            {
                currentConsumption = 0f;
                driveStatus = breedingModeEnabled ? "Breeding" : "Standby";
            }
        }

        private void UpdateBreeding()
        {
            if (!breedingModeEnabled || _engineRunning) return;
            if (currentSolarFlux < breedingMinFlux) return;

            // Only breed if there is capacity
            var astrophageRes = part.Resources["Astrophage"];
            if (astrophageRes == null) return;

            double available = astrophageRes.maxAmount - astrophageRes.amount;
            if (available <= 0) return;

            double grown = Math.Min(breedingRate * TimeWarp.fixedDeltaTime, available);
            astrophageRes.amount += grown;
        }

        private void UpdateLight()
        {
            if (_engineLight == null) return;

            float targetIntensity = _throttle * 6f;
            float targetRange     = _throttle * 80f;

            _engineLight.intensity = Mathf.Lerp(_engineLight.intensity, targetIntensity, 0.1f);
            _engineLight.range     = Mathf.Lerp(_engineLight.range,     targetRange,     0.1f);

            // Subtle colour shift: low thrust = orange, high thrust = blue-white (Cherenkov-like)
            _engineLight.color = Color.Lerp(
                new Color(1f, 0.55f, 0.1f),
                new Color(0.7f, 0.85f, 1f),
                _throttle
            );
        }

        // ── KSP Events ────────────────────────────────────────────────────

        [KSPEvent(guiActive = true, guiName = "Toggle Breeding Mode", guiActiveEditor = false)]
        public void ToggleBreeding()
        {
            breedingModeEnabled = !breedingModeEnabled;
            ScreenMessages.PostScreenMessage(
                breedingModeEnabled
                    ? "Astrophage Breeding Mode: ENABLED — organisms will multiply near stars."
                    : "Astrophage Breeding Mode: DISABLED.",
                4f,
                ScreenMessageStyle.UPPER_CENTER
            );
        }

        [KSPAction("Toggle Breeding Mode")]
        public void ToggleBreedingAction(KSPActionParam param) => ToggleBreeding();
    }
}
