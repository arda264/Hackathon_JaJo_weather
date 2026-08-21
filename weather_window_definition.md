# Weather window definition

This is a weather window definition for sailing the distance from Lowestoft to IJmuiden.

## Area of interest
The area of interest is the polygon specified in the track_area.geojson

Sample point data output is the center point of the area of interest polygon.

## Wind conditions
Wind is the main parameter to determine the weather window.

The weather window for wind is defined based on wind speed and wind direction.

- The wind speed needs to be between 18 to 30 knots. 
- The wind direction can be either from 205 to 235 degrees North, or between 305 to 335 degrees North.

Make sure to convert m/s to knots and back based on metadata of the data files. If you did the conversion, always mention it to the user.

## Wave conditions

Always ask the user explicitly if they want to include wave conditions in the weather window assessment (unless they already said it).

Wave weather window is based on three parameters:
- Wave direction (coming from) should be between 180 and 360 degrees North. 
- 



