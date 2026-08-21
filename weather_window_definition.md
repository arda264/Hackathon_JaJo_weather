# Weather window definition

This is a weather window definition for sailing the distance from Lowestoft to IJmuiden.

The sailing track is from West to East - this defines the boat sailing direction.

The user is the sailing navigrator.

The weather window is mainly determined by the wind speed and wind direction. The wind direction and wind speed have to fall in the specified weather window ranges.

If the wind weather window condition is met, we need to check waves and currents conditons and provide a summary to the user.

## Area of interest
The area of interest is the polygon specified in the area_of_interest.geojson

## Wind conditions
Wind is the main parameter to determine the weather window.

The weather window for wind is defined based on wind speed and wind direction.

- The wind speed needs to be between 18 to 30 knots. 
- The wind direction can be either from 205 to 235 degrees North, or between 305 to 335 degrees North.

Make sure to convert m/s to knots and back based on metadata of the data files. If you did the conversion, always mention it to the user.

## Wave conditions

The wave conditions are not restricted by strict limits, but the user wants to know quantitatively which conditions to expect.

The forecast gives us wave height, period and direction for wind-sea and swell waves.

Warnings triggered:
- Wave heights of above 2 m for wind-sea wave conditions should trigger a warning of potentially too high waves.
- Wave heights that are higher than 0.5 m and are opposing to the sailing direction (between 0 and 180 degrees North in absolute terms) should trigger a warning of opposing waves.
- Wind-sea wave heights of above 1m with steepness of above 0.05 should trigger a warning of steep wind-sea waves.

The user wants to know:
- Are there any wave-related warnings based on definitions above?
- How high are the wind-sea waves, which direction do they come from (absolute direction and relative to the boat direction)?
- Are there significant swell waves? Which direction do they come from and how high are they?

Wave steepness interpretation:
| Steepness       | Description     | Sailing implication                                                   |
| --------------- | --------------- | --------------------------------------------------------------------- |
| **< 0.015**     | Very low        | Long swell, gentle motion                                             |
| **0.015-0.030** | Moderate        | Generally pleasant sailing                                            |
| **0.030-0.050** | Steep           | Noticeable impacts and reduced comfort                                |
| **0.050-0.070** | Very steep      | Frequent pounding/slamming, speed losses possible                     |
| **> 0.070**     | Extremely steep | Close to breaking conditions, uncomfortable and potentially hazardous |

## Tidal current conditions

The tidal current conditions are not limiting for the sailing weather window.
But they are a useful context to the user.

The user wants to know:
- During the favourable wind weather window, what is the range of tidal current conditions? 
- What are the dates and times of the peak current velocities, and is the direction of the current during this peak?





